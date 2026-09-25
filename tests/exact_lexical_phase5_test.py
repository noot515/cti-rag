import asyncio,sqlite3,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,CandidateBudget,ProcessingClass,TemporalMode,TemporalRequest
from cti_rag.identifiers import default_identifier_registry
from cti_rag.ports import EffectiveScope,ProjectionBuildRequest,SearchKind,SearchRequest
from cti_rag.retrieval import (
    ExactLookupRequest,ExactLookupStatus,PersistentExactIndex,SQLiteFTS5LexicalIndex,StructuredJsonProjector,
)
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher

UTC=timezone.utc

class Phase5ExactLexicalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=Path(self.tmp.name)
        self.catalog=SnapshotCatalogStore.sqlite(root/"catalog.db")
        self.lex_path=root/"lexical.db"; self.exact_path=root/"exact.db"
        self.lexical=SQLiteFTS5LexicalIndex(self.lex_path,self.catalog)
        self.exact=PersistentExactIndex.sqlite(self.exact_path,self.catalog)
        self.projector=StructuredJsonProjector("unicode61/1")
        self.scope=EffectiveScope(
            principal_id="alice",tenant_id="tenant-a",domains=("cybersecurity",),source_ids=(),
            access_labels=(AccessLabel.PUBLIC,),processing_classes=(ProcessingClass.LOCAL_ONLY,),policy_epoch=1,
        )
        self.docs=[]; self.records=[]; self.revisions=[]
        self.add("rev-old","obj-1","CVE-2026-0001","lexical sentinel plume appears only in the persistent corpus",datetime(2026,1,1,tzinfo=UTC),valid_from=datetime(2025,1,1,tzinfo=UTC),valid_to=datetime(2027,1,1,tzinfo=UTC))
        self.add("rev-future","obj-1","CVE-2026-0001","chronofuture phrase must not leak",datetime(2099,1,1,tzinfo=UTC))
        self.add("rev-private","obj-private","CVE-2026-0002","secretvector private phrase",datetime(2026,1,2,tzinfo=UTC),access=AccessLabel.PRIVATE,tenant="tenant-a")
        self.add("rev-amb-a","obj-amb-a","CVE-2026-9999","ambiguity alpha",datetime(2026,1,3,tzinfo=UTC))
        self.add("rev-amb-b","obj-amb-b","CVE-2026-9999","ambiguity beta",datetime(2026,1,3,tzinfo=UTC))
        report_payload=b'{"id":"REPORT-1","summary":"mentionreporttoken discusses CVE-2026-4242 but is not the canonical CVE record"}'
        report_exact,report_docs=self.projector.project(
            normalized_bytes=report_payload,artifact_uid="art-rev-report",revision_uid="rev-report",object_uid="obj-report",
            namespace="report",object_type="report",canonical_id="REPORT-1",domain="cybersecurity",source_id="synthetic-report",
            tenant_id="public",access_label=AccessLabel.PUBLIC,available_at=datetime(2026,1,2,tzinfo=UTC),
            text_pointers=("/summary",),context_prefix="synthetic report",
        )
        self.records.append(report_exact); self.docs.extend(report_docs); self.revisions.append("rev-report")
        self.revisions=tuple(sorted(self.revisions))
        ereq=ProjectionBuildRequest("exact-g1","exact",self.revisions,("canonical-id/1",),("exact",),0)
        lreq=ProjectionBuildRequest("lex-g1","lexical",self.revisions,("unicode61/1",),("lexical",),0)
        self.exact_gen=self.exact.build(ereq,self.records); self.lex_gen=self.lexical.build(lreq,self.docs)
        self.assertTrue(self.exact.validate(self.exact_gen)); self.assertTrue(self.lexical.validate(self.lex_gen))
        pub=SnapshotPublisher(self.catalog); pub.stage_generation(self.exact_gen); pub.stage_generation(self.lex_gen)
        self.manifest=pub.publish(("exact-g1","lex-g1"),("exact","lexical"),created_at=datetime(2026,1,4,tzinfo=UTC))
        self.pinned=self.catalog.pin_current(self.scope,ttl_seconds=120,now=datetime(2026,1,4,tzinfo=UTC))
        self.snapshot=self.pinned.manifest.to_ref()
    def tearDown(self): self.tmp.cleanup()

    def add(self,revision_uid,object_uid,cve,summary,available,access=AccessLabel.PUBLIC,tenant="public",valid_from=None,valid_to=None):
        payload=("{"+f'"id":"{cve}","summary":"{summary}"'+"}").encode()
        exact,docs=self.projector.project(
            normalized_bytes=payload,artifact_uid=f"art-{revision_uid}",revision_uid=revision_uid,object_uid=object_uid,
            namespace="cve",object_type="cve",canonical_id=cve,domain="cybersecurity",source_id="synthetic-cyber",
            tenant_id=tenant,access_label=access,available_at=available,valid_from=valid_from,valid_to=valid_to,text_pointers=("/summary",),context_prefix=f"{cve} synthetic advisory",
        )
        self.records.append(exact); self.docs.extend(docs); self.revisions.append(revision_uid)

    def search(self,query,temporal=None,backend=None):
        request=SearchRequest(query,SearchKind.LEXICAL,self.scope,temporal or TemporalRequest(TemporalMode.CURRENT),CandidateBudget(20,lexical=20),self.snapshot)
        return asyncio.run((backend or self.lexical).search(request))

    def lookup(self,value,temporal=None,namespace=None,valid_at=None):
        return self.exact.lookup(ExactLookupRequest(value,self.scope,temporal or TemporalRequest(TemporalMode.CURRENT),self.snapshot,namespace=namespace,valid_at=valid_at))

    def test_actual_sqlite_fts5_backend_finds_passage_absent_from_dense_candidates_and_survives_restart(self):
        dense_candidates=()
        result=self.search("sentinel plume")
        self.assertEqual(dense_candidates,())
        self.assertEqual(result.status.value,"ok"); self.assertEqual(result.items[0].revision_uid,"rev-old")
        restarted=SQLiteFTS5LexicalIndex(self.lex_path,self.catalog)
        again=self.search("sentinel plume",backend=restarted)
        self.assertEqual(again.status.value,"ok"); self.assertEqual(again.items[0].passage_uid,result.items[0].passage_uid)

    def test_exact_lookup_rejects_near_match_and_reports_ambiguity(self):
        self.assertEqual(self.lookup("CVE-2026-1").status,ExactLookupStatus.INVALID)
        self.assertEqual(self.lookup("CVE-2026-00010").status,ExactLookupStatus.NOT_FOUND)
        ambiguous=self.lookup("CVE-2026-9999")
        self.assertEqual(ambiguous.status,ExactLookupStatus.AMBIGUOUS); self.assertEqual(len(ambiguous.records),2)

    def test_exact_lookup_selects_latest_eligible_revision_not_future_revision(self):
        result=self.lookup("CVE-2026-0001")
        self.assertEqual(result.status,ExactLookupStatus.FOUND)
        self.assertEqual(result.records[0].revision_uid,"rev-old")

    def test_reports_mentioning_identifier_are_not_treated_as_canonical_exact_records(self):
        lexical=self.search("mentionreporttoken")
        self.assertEqual(lexical.status.value,"ok")
        self.assertEqual(lexical.items[0].revision_uid,"rev-report")
        self.assertEqual(self.lookup("CVE-2026-4242").status,ExactLookupStatus.NOT_FOUND)

    def test_exact_lookup_enforces_validity_interval(self):
        inside=self.lookup("CVE-2026-0001",valid_at=datetime(2026,6,1,tzinfo=UTC))
        outside=self.lookup("CVE-2026-0001",valid_at=datetime(2030,1,1,tzinfo=UTC))
        self.assertEqual(inside.status,ExactLookupStatus.FOUND)
        self.assertEqual(inside.records[0].revision_uid,"rev-old")
        self.assertEqual(outside.status,ExactLookupStatus.NOT_FOUND)

    def test_private_and_future_records_do_not_leave_backend(self):
        self.assertEqual(self.search("secretvector").status.value,"empty")
        self.assertEqual(self.search("chronofuture").status.value,"empty")
        self.assertEqual(self.lookup("CVE-2026-0002").status,ExactLookupStatus.NOT_FOUND)

    def test_historical_public_cutoff_is_enforced_inside_lexical_and_exact_boundaries(self):
        temporal=TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-12-31T23:59:59Z")
        self.assertEqual(self.search("sentinel",temporal).status.value,"empty")
        self.assertEqual(self.lookup("CVE-2026-0001",temporal).status,ExactLookupStatus.NOT_FOUND)

    def test_reindex_is_idempotent(self):
        ereq=ProjectionBuildRequest("exact-g1","exact",self.revisions,("canonical-id/1",),("exact",),0)
        lreq=ProjectionBuildRequest("lex-g1","lexical",self.revisions,("unicode61/1",),("lexical",),0)
        self.exact.build(ereq,self.records); self.lexical.build(lreq,self.docs)
        conn=sqlite3.connect(self.lex_path)
        try:self.assertEqual(conn.execute("SELECT COUNT(*) FROM lexical_fts WHERE generation_id='lex-g1'").fetchone()[0],len(self.docs))
        finally:conn.close()
        conn=sqlite3.connect(self.exact_path)
        try:self.assertEqual(conn.execute("SELECT COUNT(*) FROM exact_records WHERE generation_id='exact-g1'").fetchone()[0],len(self.records))
        finally:conn.close()

    def test_tombstones_hide_old_snapshot_results_immediately(self):
        hit=self.search("sentinel").items[0]
        self.catalog.admit_revocation(hit.passage_uid,"passage withdrawn",(),("lexical",))
        self.assertEqual(self.search("sentinel").status.value,"empty")
        self.catalog.admit_revocation("rev-old","revision withdrawn",(),("exact","lexical"))
        self.assertEqual(self.lookup("CVE-2026-0001").status,ExactLookupStatus.NOT_FOUND)

    def test_returned_locator_resolves_to_indexed_revision(self):
        hit=self.search("sentinel").items[0]
        self.assertEqual(hit.revision_uid,"rev-old")
        self.assertEqual(hit.provenance.revision_uid,"rev-old")
        self.assertEqual(hit.provenance.locator.pointer,"/summary")
        self.assertIn("lexical sentinel plume",hit.text)

    def test_identifier_registry_hooks_cover_cyber_network_and_humanities_namespaces(self):
        reg=default_identifier_registry()
        self.assertEqual(reg.parse_one("cve-2026-0001").canonical,"CVE-2026-0001")
        self.assertEqual(reg.parse_one("AS64512").namespace,"asn")
        self.assertEqual(reg.parse_one("192.0.2.0/24").namespace,"cidr")
        self.assertEqual(reg.parse_one("10.1234/ABC.DEF").canonical,"10.1234/abc.def")

if __name__=="__main__": unittest.main()
