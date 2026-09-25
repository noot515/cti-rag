import asyncio,sqlite3,tempfile,unittest
from pathlib import Path
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore,canonical_store_from_legacy_manager
from cti_rag.ingestion import IngestionPipeline,OutboxWorker,SYNTHETIC_MANIFEST,SyntheticCyberConnector,SyntheticCyberNormalizer
from cti_rag.ports import SourceRecord

class Phase3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name); self.db=root/"meta.db"; self.obj=FileObjectStore(root/"objects",max_object_bytes=1024*1024); self.meta=CanonicalMetadataStore.sqlite(self.db,object_exists=self.obj.exists)
    def tearDown(self): self.tmp.cleanup()
    def pipeline(self,records=None,page_size=16,objects=None,meta=None): return IngestionPipeline(SYNTHETIC_MANIFEST,SyntheticCyberConnector(records,page_size),SyntheticCyberNormalizer(),objects or self.obj,meta or self.meta)
    def ids(self,table,column):
        conn=sqlite3.connect(self.db)
        try:return tuple(r[0] for r in conn.execute(f"SELECT {column} FROM {table} ORDER BY {column}"))
        finally:conn.close()

    def test_replay_yields_identical_logical_evidence_state(self):
        p=self.pipeline(); asyncio.run(p.ingest_page(None)); first=self.meta.counts(); asyncio.run(p.ingest_page(None)); second=self.meta.counts()
        for key in ("raw_snapshots","source_objects","revisions","artifacts","retrieval_observations","outbox","quarantines"): self.assertEqual(first[key],second[key],key)
        self.assertEqual(second["artifacts"],2)

    def test_interrupt_before_metadata_commit_leaves_orphan_and_does_not_advance_cursor(self):
        p=self.pipeline()
        with self.assertRaisesRegex(RuntimeError,"after_raw_stage"): asyncio.run(p.ingest_page(None,failpoint="after_raw_stage"))
        self.assertIsNone(self.meta.checkpoint(SYNTHETIC_MANIFEST.source_id)); self.assertEqual(self.meta.counts()["artifacts"],0); self.assertEqual(len(p.orphan_objects()),1)
        asyncio.run(p.ingest_page(None)); self.assertIsNotNone(self.meta.checkpoint(SYNTHETIC_MANIFEST.source_id)); self.assertEqual(self.meta.counts()["artifacts"],2); self.assertEqual(len(p.orphan_objects()),0)

    def test_interrupt_after_metadata_commit_resumes_without_duplicate(self):
        p=self.pipeline()
        with self.assertRaisesRegex(RuntimeError,"after_metadata_commit"): asyncio.run(p.ingest_page(None,failpoint="after_metadata_commit"))
        self.assertEqual(self.meta.counts()["artifacts"],1); self.assertIsNone(self.meta.checkpoint(SYNTHETIC_MANIFEST.source_id))
        asyncio.run(p.ingest_page(None)); self.assertEqual(self.meta.counts()["artifacts"],2); self.assertEqual(self.meta.counts()["outbox"],2); self.assertIsNotNone(self.meta.checkpoint(SYNTHETIC_MANIFEST.source_id))

    def test_corrupt_and_poison_records_are_quarantined_without_losing_valid_sibling(self):
        valid=SourceRecord("CVE-2026-0100",b'{"id":"CVE-2026-0100","summary":"valid","published_at":"2026-01-03T00:00:00Z"}',"1")
        corrupt=SourceRecord("CVE-2026-0101",b'{"id":"CVE-2026-0101","summary":"checksum","published_at":"2026-01-03T00:00:00Z"}',"1",claimed_digest="0"*64)
        poison=SourceRecord("CVE-2026-0102",b'not-json',"1")
        result=asyncio.run(self.pipeline((valid,corrupt,poison),3).ingest_page(None))
        self.assertEqual(result["accepted"],1); self.assertEqual(result["quarantined"],2); self.assertEqual(self.meta.counts()["artifacts"],1); self.assertEqual(self.meta.counts()["quarantines"],2); self.assertIsNotNone(self.meta.checkpoint(SYNTHETIC_MANIFEST.source_id))

    def test_canonical_metadata_refuses_missing_object_reference(self):
        class BrokenExists:
            def __init__(self,base): self.base=base
            def put(self,*a,**k): return self.base.put(*a,**k)
            def exists(self,*a,**k): return False
            def orphan_refs(self,*a,**k): return self.base.orphan_refs(*a,**k)
        broken=BrokenExists(self.obj); meta=CanonicalMetadataStore.sqlite(Path(self.tmp.name)/"broken.db",object_exists=broken.exists); p=self.pipeline(objects=broken,meta=meta)
        with self.assertRaises(FileNotFoundError): asyncio.run(p.ingest_page(None))
        self.assertEqual(meta.counts()["artifacts"],0); self.assertIsNone(meta.checkpoint(SYNTHETIC_MANIFEST.source_id))

    def test_deletion_dependencies_are_enumerable_and_cleanup_event_is_idempotent(self):
        p=self.pipeline(); asyncio.run(p.ingest_page(None)); object_uid=self.ids("source_objects","object_uid")[0]; deps=self.meta.dependents(object_uid); self.assertEqual(len(deps),2)
        revision_uid=self.ids("revisions","revision_uid")[0]; before=self.meta.counts()["outbox"]; a=self.meta.add_revocation(revision_uid,"fixture-delete"); b=self.meta.add_revocation(revision_uid,"fixture-delete"); self.assertEqual(a,b); self.assertEqual(self.meta.counts()["revocations"],1); self.assertEqual(self.meta.counts()["outbox"],before+1)

    def test_outbox_is_at_least_once_with_deterministic_idempotency_key(self):
        asyncio.run(self.pipeline().ingest_page(None)); calls=[]; effects=set()
        def handler(event,key): calls.append(key); effects.add(key)
        worker=OutboxWorker(self.meta,handler,max_attempts=3)
        with self.assertRaises(SystemExit): worker.drain_once(limit=1,crash_after_handler=True)
        worker.drain_once(limit=1); self.assertEqual(len(calls),2); self.assertEqual(calls[0],calls[1]); self.assertEqual(len(effects),1)

    def test_poison_outbox_event_dead_letters_after_bounded_retries(self):
        asyncio.run(self.pipeline().ingest_page(None)); worker=OutboxWorker(self.meta,lambda e,k: (_ for _ in ()).throw(RuntimeError("poison")),max_attempts=2)
        worker.drain_once(limit=1); worker.drain_once(limit=1); self.assertEqual(self.meta.counts()["dead_letters"],1)

    def test_existing_manager_adapter_reuses_configured_engine_connection(self):
        db2=Path(self.tmp.name)/"legacy-pool.db"
        class Dialect: name="sqlite"
        class Engine:
            dialect=Dialect()
            def raw_connection(self): return sqlite3.connect(db2)
        class Manager: engine=Engine()
        store=canonical_store_from_legacy_manager(Manager(),self.obj); store.put_manifest(SYNTHETIC_MANIFEST); self.assertEqual(store.counts()["source_manifests"],1)

if __name__=="__main__":unittest.main()
