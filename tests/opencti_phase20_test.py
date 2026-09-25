from __future__ import annotations
import asyncio,copy,json,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,ProcessingClass,canonical_json_bytes
from cti_rag.domains.cybersecurity import (
    ATTACK_STIX_FIXTURE,AttackStixConnector,AttackStixNormalizer,
    OPENCTI_MANIFEST,OPENCTI_OBJECT_METADATA,OPENCTI_OBJECT_STIX,
    OPENCTI_RELATION_METADATA,OPENCTI_RELATION_STIX,OpenCTIImportedStixNormalizer,
)
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.infrastructure.opencti import OpenCTIReadConnector,OpenCTIUnavailable
from cti_rag.ingestion import IngestionPipeline
from cti_rag.snapshots import ProjectionGeneration,SnapshotCatalogStore,SnapshotPublisher

class FakeList:
    def __init__(self,pages,owner):self.pages=pages;self.owner=owner
    def list(self,**kwargs):
        self.owner.read_calls+=1
        if self.owner.fail_reads:raise ConnectionError("fixture outage")
        after=kwargs.get("after");page=self.pages.get(after)
        if page is None:return {"entities":[],"pagination":{"hasNextPage":False,"endCursor":None}}
        return copy.deepcopy(page)

class FakeOpenCTI:
    def __init__(self,objects=None,relationships=None,stix=None):
        self.read_calls=0;self.write_calls=0;self.fail_reads=False
        self.stix_core_object=FakeList(objects or {None:{"entities":[],"pagination":{"hasNextPage":False,"endCursor":None}}},self)
        self.stix_core_relationship=FakeList(relationships or {None:{"entities":[],"pagination":{"hasNextPage":False,"endCursor":None}}},self)
        self.stix=stix or {}
    def get_stix_content(self,ident):
        self.read_calls+=1
        if self.fail_reads:raise ConnectionError("fixture outage")
        return copy.deepcopy(self.stix[ident])
    def create(self,*args,**kwargs):self.write_calls+=1;raise AssertionError("write API must never be used")
    def delete(self,*args,**kwargs):self.write_calls+=1;raise AssertionError("write API must never be used")

def fixture_client(metadata=None,stix=None,relationship=True):
    metadata=copy.deepcopy(metadata or OPENCTI_OBJECT_METADATA);stix=copy.deepcopy(stix or OPENCTI_OBJECT_STIX)
    objects={None:{"entities":[metadata],"pagination":{"hasNextPage":False,"endCursor":None}}}
    relationships={None:{"entities":[copy.deepcopy(OPENCTI_RELATION_METADATA)] if relationship else [],"pagination":{"hasNextPage":False,"endCursor":None}}}
    bodies={metadata["id"]:stix}
    if relationship:bodies[OPENCTI_RELATION_METADATA["id"]]=copy.deepcopy(OPENCTI_RELATION_STIX)
    return FakeOpenCTI(objects,relationships,bodies)

async def all_pages(connector):
    cursor=None;pages=[]
    while True:
        page=await connector.fetch_page(cursor);pages.append(page)
        if page.exhausted:return pages
        cursor=page.next_cursor

class OpenCTIPhase20Test(unittest.TestCase):
    def test_minimal_requirements_and_domain_import_do_not_require_pycti(self):
        root=Path(__file__).resolve().parents[1]
        for path in (root/"cti_rag"/"contracts",root/"cti_rag"/"domains",root/"cti_rag"/"planning"):
            for source in path.rglob("*.py"):
                self.assertNotIn("import pycti",source.read_text(encoding="utf-8"),source)
                self.assertNotIn("from pycti",source.read_text(encoding="utf-8"),source)
        for name in ("requirements.txt","requirements-api.txt","requirements-research.txt","requirements-worker.txt"):
            self.assertNotIn("pycti",(root/name).read_text(encoding="utf-8").lower())

    def test_bounded_pagination_reads_objects_then_relationships_without_writes(self):
        client=fixture_client();connector=OpenCTIReadConnector(client,page_size=1)
        pages=asyncio.run(all_pages(connector))
        self.assertEqual(2,len(pages));self.assertEqual(1,len(pages[0].records));self.assertEqual(1,len(pages[1].records))
        self.assertTrue(pages[-1].exhausted);self.assertGreater(client.read_calls,0);self.assertEqual(0,client.write_calls)
        body=json.loads(pages[0].records[0].raw_bytes)
        self.assertEqual(OPENCTI_OBJECT_STIX["id"],body["stix"]["id"]);self.assertEqual(OPENCTI_OBJECT_METADATA["id"],body["opencti"]["id"])

    def test_supported_markings_are_most_restrictive_and_unknown_is_rejected(self):
        normalizer=OpenCTIImportedStixNormalizer("tenant-a")
        record=asyncio.run(OpenCTIReadConnector(fixture_client(),page_size=1).fetch_page()).records[0]
        normalized=normalizer.normalize(record)
        self.assertEqual(AccessLabel.PUBLIC,normalized.policy.access_label)
        red_meta=copy.deepcopy(OPENCTI_OBJECT_METADATA);red_meta["objectMarking"].append(copy.deepcopy(OPENCTI_RELATION_METADATA["objectMarking"][0]))
        red_record=asyncio.run(OpenCTIReadConnector(fixture_client(red_meta),page_size=1).fetch_page()).records[0]
        self.assertEqual(AccessLabel.RESTRICTED,normalizer.normalize(red_record).policy.access_label)
        self.assertEqual(ProcessingClass.LOCAL_ONLY,normalizer.normalize(red_record).policy.processing_class)
        bad=copy.deepcopy(OPENCTI_OBJECT_METADATA);bad["objectMarking"]=[{"id":"custom","standard_id":"marking--custom","definition_type":"CUSTOM","definition":"PARTNERS"}]
        bad_record=asyncio.run(OpenCTIReadConnector(fixture_client(bad),page_size=1).fetch_page()).records[0]
        with self.assertRaisesRegex(ValueError,"unsupported mandatory"):normalizer.normalize(bad_record)

    def test_relationship_marking_cannot_be_lowered_by_alias_or_endpoint_identity(self):
        pages=asyncio.run(all_pages(OpenCTIReadConnector(fixture_client(),page_size=1)))
        relationship=OpenCTIImportedStixNormalizer("tenant-a").normalize(pages[1].records[0])
        body=json.loads(relationship.normalized_bytes)
        self.assertEqual(AccessLabel.RESTRICTED,relationship.policy.access_label)
        self.assertEqual("relationship",body["stix_type"]);self.assertEqual("imported_source",body["assertion_origin"])
        self.assertFalse(body["locally_extracted_hypothesis"])
        self.assertEqual(OPENCTI_RELATION_STIX["source_ref"],body["source_ref"])

    def test_replay_is_idempotent_and_update_creates_new_revision(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists)
            async def ingest(client):
                pipeline=IngestionPipeline(OPENCTI_MANIFEST,OpenCTIReadConnector(client,page_size=1),OpenCTIImportedStixNormalizer("tenant-a"),objects,meta)
                cursor=None
                while True:
                    result=await pipeline.ingest_page(cursor)
                    if result["exhausted"]:break
                    cursor=result["next_cursor"]
            asyncio.run(ingest(fixture_client()))
            first=meta.counts()
            asyncio.run(ingest(fixture_client()))
            self.assertEqual(first,meta.counts())
            changed_meta=copy.deepcopy(OPENCTI_OBJECT_METADATA);changed_meta["updated_at"]="2026-02-02T00:00:00.000Z"
            changed_stix=copy.deepcopy(OPENCTI_OBJECT_STIX);changed_stix["modified"]="2026-02-02T00:00:00.000Z";changed_stix["description"]="Updated imported source assertion."
            asyncio.run(ingest(fixture_client(changed_meta,changed_stix)))
            self.assertGreater(meta.counts()["revisions"],first["revisions"])

    def test_completed_sync_emits_missing_and_revoked_tombstones(self):
        client=fixture_client();connector=OpenCTIReadConnector(client,page_size=1,previous_ids=(OPENCTI_OBJECT_STIX["id"],"malware--00000000-0000-4000-8000-999999999999"))
        pages=asyncio.run(all_pages(connector));missing={d.stable_upstream_id for d in pages[-1].deletions}
        self.assertIn("malware--00000000-0000-4000-8000-999999999999",missing)
        revoked=copy.deepcopy(OPENCTI_OBJECT_STIX);revoked["revoked"]=True
        revoked_pages=asyncio.run(all_pages(OpenCTIReadConnector(fixture_client(stix=revoked),page_size=1)))
        deleted={d.stable_upstream_id for p in revoked_pages for d in p.deletions}
        self.assertIn(revoked["id"],deleted)

    def test_resumed_cursor_does_not_infer_deletions_from_unseen_earlier_pages(self):
        connector=OpenCTIReadConnector(fixture_client(),page_size=1,previous_ids=("missing--would-be-dangerous",))
        first=asyncio.run(connector.fetch_page(None))
        fresh=OpenCTIReadConnector(fixture_client(),page_size=1,previous_ids=("missing--would-be-dangerous",))
        resumed=asyncio.run(fresh.fetch_page(first.next_cursor))
        self.assertTrue(resumed.exhausted);self.assertEqual((),resumed.deletions)

    def test_service_failure_is_explicit_and_published_snapshot_is_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            catalog=SnapshotCatalogStore.sqlite(Path(td)/"catalog.db");now=datetime.now(timezone.utc)
            generation=ProjectionGeneration("g1","lexical",("r1",),("fixture/1",),"checksum",True,True,True,0,("lexical",),now)
            publisher=SnapshotPublisher(catalog);publisher.stage_generation(generation);manifest=publisher.publish(("g1",),("lexical",),created_at=now)
            client=fixture_client();client.fail_reads=True
            with self.assertRaises(OpenCTIUnavailable):asyncio.run(OpenCTIReadConnector(client,max_retries=1).fetch_page(None))
            self.assertEqual(manifest.manifest_id,catalog.current_manifest().manifest_id)

    def test_direct_source_and_opencti_fixture_are_related_but_not_collapsed(self):
        direct_record=asyncio.run(AttackStixConnector(page_size=10).fetch_page()).records[0]
        direct=AttackStixNormalizer().normalize(direct_record)
        imported_record=asyncio.run(OpenCTIReadConnector(fixture_client(),page_size=1).fetch_page()).records[0]
        imported=OpenCTIImportedStixNormalizer("tenant-a").normalize(imported_record)
        direct_body=json.loads(direct.normalized_bytes);imported_body=json.loads(imported.normalized_bytes)
        self.assertEqual(direct_body["name"],imported_body["name"])
        self.assertNotEqual(direct.stable_upstream_id,imported.stable_upstream_id)
        self.assertEqual(OPENCTI_OBJECT_STIX["id"],dict((x.name,x.value) for x in imported.identity_attributes)["stix_id"])
        self.assertEqual("imported_source",imported_body["assertion_origin"])

if __name__=="__main__":unittest.main()
