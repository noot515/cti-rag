import asyncio,json,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import AccessLabel,CandidateBudget,ProcessingClass,TemporalMode,TemporalRequest
from cti_rag.domains.cybersecurity import (
    ATTACK_MANIFEST,CVE_MANIFEST,KEV_MANIFEST,ATTACK_STIX_FIXTURE,ATTACK_STIX_REVOKED_FIXTURE,CVE_V5_FIXTURE,CVE_V5_UPDATED_FIXTURE,INVALID_STIX_FIXTURE,KEV_FIXTURE,
    AttackStixConnector,AttackStixNormalizer,CveJsonV5Normalizer,CveListConnector,CyberProjectionRebuilder,CyberSourceLifecycle,KevConnector,KevNormalizer,
    SourceAdapterStatus,cyber_dataset_registry,source_coverage_matrix
)
from cti_rag.graph import EntityResolutionJournal,ReferenceGraphPort,TraversalStep,TraversalTemplate
from cti_rag.infrastructure import CanonicalMetadataStore,FileObjectStore
from cti_rag.ingestion import IngestionPipeline
from cti_rag.ports import (
    ChannelStatus,EffectiveScope,GraphRequest,ProjectionBuildRequest,SearchKind,SearchRequest,StructuredRequest
)
from cti_rag.retrieval import PersistentExactIndex,SQLiteFTS5LexicalIndex
from cti_rag.retrieval.models import ExactLookupRequest,ExactLookupStatus
from cti_rag.snapshots import RevocationCoordinator,SnapshotCatalogStore,SnapshotPublisher
from cti_rag.structured import DuckDBStructuredPort,Predicate,PredicateOperator,StructuredQuerySpec

UTC=timezone.utc
NOW=datetime(2026,3,1,tzinfo=UTC)
SCOPE=EffectiveScope("alice","public",("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

class SupportStore:
    def __init__(self,revisions):self.revisions=set(revisions)
    def resolve(self,ref):return b"source-backed" if ref.revision_uid in self.revisions else None
    def get_revision(self,uid):return None
    def get_artifact(self,uid):return None
    def get_passage(self,uid):return None
    def dependents(self,uid):return ()

def runtime(td):
    root=Path(td);objects=FileObjectStore(root/"objects");meta=CanonicalMetadataStore.sqlite(root/"meta.db",object_exists=objects.exists);catalog=SnapshotCatalogStore.sqlite(root/"catalog.db");rev=RevocationCoordinator(catalog,meta)
    return objects,meta,catalog,rev

class Phase11CyberSourceTests(unittest.TestCase):
    def test_core_real_format_normalizers_and_coverage_matrix_are_honest(self):
        attack_page=asyncio.run(AttackStixConnector().fetch_page(None));tech=next(r for r in attack_page.records if b'"attack-pattern"' in r.raw_bytes)
        attack=AttackStixNormalizer().normalize(tech);self.assertEqual((attack.stable_upstream_id,attack.upstream_object_type),("T9001","attack-technique"))
        cve=CveJsonV5Normalizer().normalize(CveListConnector().records and __import__("cti_rag.ports",fromlist=["SourceRecord"]).SourceRecord("c",CVE_V5_FIXTURE,"1"))
        body=json.loads(cve.normalized_bytes);self.assertEqual(body["id"],"CVE-2099-0001")
        self.assertEqual({(m["source_container"],m["scheme"],m["base_score"]) for m in body["cvss"]},{("cna","CVSS:3.1",8.8),("adp","CVSS:3.1",7.5)})
        kev_page=asyncio.run(KevConnector().fetch_page(None));kev=KevNormalizer().normalize(kev_page.records[0]);self.assertEqual(json.loads(kev.normalized_bytes)["date_added"],"2026-01-05")
        matrix={x.source_id:x for x in source_coverage_matrix()}
        for source_id in ("mitre-attack-stix","cve-list-v5","cisa-kev"):
            self.assertEqual(matrix[source_id].status,SourceAdapterStatus.FIXTURE_VALIDATED);self.assertTrue(matrix[source_id].connector and matrix[source_id].normalizer)
        for source_id in ("nvd","ghsa","cwe","capec","d3fend","atlas","car","attack-flow","misp","sigma","atomic-red-team","cvefixes","megavul","poc-metadata","soc-corpora"):
            self.assertEqual(matrix[source_id].status,SourceAdapterStatus.DEFERRED);self.assertTrue(matrix[source_id].reason)

    def test_invalid_stix_and_missing_mapping_evidence_are_quarantined(self):
        malformed=b'{"dataType":"CVE_RECORD","dataVersion":"5.2","cveMetadata":{"cveId":"CVE-2099-0002","state":"PUBLISHED","datePublished":"2026-01-01T00:00:00Z","dateUpdated":"2026-01-01T00:00:00Z"},"containers":{"cna":{"descriptions":[{"lang":"en","value":"x"}],"problemTypes":[{"descriptions":[{"lang":"en","type":"CWE","description":"missing id"}]}],"metrics":[]}}}'
        with tempfile.TemporaryDirectory() as td:
            objects,meta,_catalog,_rev=runtime(td)
            bad_stix=asyncio.run(CyberSourceLifecycle(IngestionPipeline(ATTACK_MANIFEST,AttackStixConnector(INVALID_STIX_FIXTURE),AttackStixNormalizer(),objects,meta)).ingest_all())
            bad_cve=asyncio.run(CyberSourceLifecycle(IngestionPipeline(CVE_MANIFEST,CveListConnector((malformed,)),CveJsonV5Normalizer(),objects,meta)).ingest_all())
            self.assertEqual((bad_stix["accepted"],bad_stix["quarantined"]),(0,1));self.assertEqual((bad_cve["accepted"],bad_cve["quarantined"]),(0,1))

    def test_cve_update_historical_lookup_tombstone_and_republish(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog,rev=runtime(td)
            first=CyberSourceLifecycle(IngestionPipeline(CVE_MANIFEST,CveListConnector((CVE_V5_FIXTURE,)),CveJsonV5Normalizer(),objects,meta,rev))
            second=CyberSourceLifecycle(IngestionPipeline(CVE_MANIFEST,CveListConnector((CVE_V5_UPDATED_FIXTURE,)),CveJsonV5Normalizer(),objects,meta,rev))
            asyncio.run(first.ingest_all());asyncio.run(second.ingest_all())
            revisions=meta.revision_uids_for_source_object("cve-list-v5","CVE-2099-0001");self.assertEqual(len(revisions),2)
            bundle=CyberProjectionRebuilder(meta,objects).rebuild(("cve-list-v5",),"source-state-1")
            exact=PersistentExactIndex.sqlite(Path(td)/"exact.db",catalog);lex=SQLiteFTS5LexicalIndex(Path(td)/"lex.db",catalog)
            revset=tuple(sorted(revisions));eg=exact.build(ProjectionBuildRequest("exact-cyber-1","exact",revset,("canonical/1",),("exact",)),bundle.exact);lg=lex.build(ProjectionBuildRequest("lex-cyber-1","lexical",revset,("unicode61/1",),("lexical",)),bundle.lexical)
            pub=SnapshotPublisher(catalog);pub.stage_generation(eg);pub.stage_generation(lg);manifest=pub.publish(("exact-cyber-1","lex-cyber-1"),("exact","lexical"),created_at=NOW);snap=manifest.to_ref()
            current=exact.lookup(ExactLookupRequest("CVE-2099-0001",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap));self.assertEqual(current.status,ExactLookupStatus.FOUND)
            self.assertIn("2026-02-03",current.records[0].available_at.isoformat())
            historical=exact.lookup(ExactLookupRequest("CVE-2099-0001",SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap));self.assertEqual(historical.status,ExactLookupStatus.FOUND);self.assertIn("2026-01-03",historical.records[0].available_at.isoformat())
            result=asyncio.run(lex.search(SearchRequest("cross-site scripting",SearchKind.LEXICAL,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),CandidateBudget(10,lexical=10),snap)))
            self.assertEqual(result.status,ChannelStatus.OK);self.assertTrue(any("Fictitious" in x.text for x in result.items))
            preserved=[objects.get(r) for r in objects.iter_refs() if b"Fictitious cross-site scripting" in objects.get(r)];self.assertTrue(preserved)
            self.assertEqual(second.delete("CVE-2099-0001","fixture upstream tombstone"),2)
            self.assertEqual(exact.lookup(ExactLookupRequest("CVE-2099-0001",SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)).status,ExactLookupStatus.NOT_FOUND)
            denied=asyncio.run(lex.search(SearchRequest("cross-site scripting",SearchKind.LEXICAL,SCOPE,TemporalRequest(TemporalMode.CURRENT),CandidateBudget(10,lexical=10),snap)));self.assertEqual(denied.status,ChannelStatus.EMPTY)
            rebuilt=CyberProjectionRebuilder(meta,objects).rebuild(("cve-list-v5",),"source-state-2");self.assertEqual((rebuilt.exact,rebuilt.lexical),((),()))
            eg2=exact.build(ProjectionBuildRequest("exact-cyber-2","exact",(),("canonical/1",),("exact",)),());lg2=lex.build(ProjectionBuildRequest("lex-cyber-2","lexical",(),("unicode61/1",),("lexical",)),())
            pub.stage_generation(eg2);pub.stage_generation(lg2);manifest2=pub.publish(("exact-cyber-2","lex-cyber-2"),("exact","lexical"),created_at=NOW)
            self.assertEqual(exact.lookup(ExactLookupRequest("CVE-2099-0001",SCOPE,TemporalRequest(TemporalMode.CURRENT),manifest2.to_ref())).status,ExactLookupStatus.NOT_FOUND)
            self.assertTrue(any(b"Fictitious cross-site scripting" in objects.get(r) for r in objects.iter_refs()))

    def test_attack_revoked_update_tombstones_preserved_revisions(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog,rev=runtime(td)
            first=CyberSourceLifecycle(IngestionPipeline(ATTACK_MANIFEST,AttackStixConnector(ATTACK_STIX_FIXTURE),AttackStixNormalizer(),objects,meta,rev))
            second=CyberSourceLifecycle(IngestionPipeline(ATTACK_MANIFEST,AttackStixConnector(ATTACK_STIX_REVOKED_FIXTURE),AttackStixNormalizer(),objects,meta,rev))
            asyncio.run(first.ingest_all());result=asyncio.run(second.ingest_all())
            revisions=meta.revision_uids_for_source_object("mitre-attack-stix","T9001");self.assertEqual(len(revisions),2);self.assertGreaterEqual(result["tombstoned"],2)
            self.assertTrue(all(catalog.is_revoked(r) for r in revisions))

    def test_kev_catalog_removal_emits_tombstone(self):
        empty=b'{"title":"Fixture","catalogVersion":"2099.02.01","dateReleased":"2026-02-01T00:00:00Z","count":0,"vulnerabilities":[]}'
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog,rev=runtime(td)
            first=CyberSourceLifecycle(IngestionPipeline(KEV_MANIFEST,KevConnector(KEV_FIXTURE),KevNormalizer(),objects,meta,rev))
            second=CyberSourceLifecycle(IngestionPipeline(KEV_MANIFEST,KevConnector(empty,previous_cve_ids=("CVE-2099-0001",)),KevNormalizer(),objects,meta,rev))
            asyncio.run(first.ingest_all());result=asyncio.run(second.ingest_all())
            revisions=meta.revision_uids_for_source_object("cisa-kev","CVE-2099-0001")
            self.assertEqual(len(revisions),1);self.assertEqual(result["tombstoned"],1);self.assertTrue(catalog.is_revoked(revisions[0]))

    def test_structured_cvss_disagreement_and_kev_eligibility_are_exact(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,_catalog,_rev=runtime(td)
            asyncio.run(CyberSourceLifecycle(IngestionPipeline(CVE_MANIFEST,CveListConnector((CVE_V5_FIXTURE,CVE_V5_UPDATED_FIXTURE)),CveJsonV5Normalizer(),objects,meta)).ingest_all())
            asyncio.run(CyberSourceLifecycle(IngestionPipeline(KEV_MANIFEST,KevConnector(KEV_FIXTURE),KevNormalizer(),objects,meta)).ingest_all())
            bundle=CyberProjectionRebuilder(meta,objects).rebuild(("cve-list-v5","cisa-kev"),"manifest-cyber")
            port=DuckDBStructuredPort(cyber_dataset_registry(bundle.structured_rows))
            from cti_rag.contracts import SnapshotManifestRef
            snap=SnapshotManifestRef("manifest-cyber","c",NOW,("structured-g",))
            spec=StructuredQuerySpec("cyber_cvss",select_fields=("cvss_scheme","cvss_score","cvss_severity","source_container"),predicates=(Predicate("cve_id",PredicateOperator.EQ,"CVE-2099-0001"),))
            current=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)));self.assertEqual(current.status,ChannelStatus.OK)
            fields={f.name:f for f in current.items[0].fields};self.assertEqual(set(fields["cvss_score"].value),{9.8,7.5});self.assertEqual(fields["cvss_score"].unit,"score");self.assertEqual(set(fields["source_container"].value),{"cna","adp"})
            old=asyncio.run(port.execute(StructuredRequest(spec,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2026-01-15T00:00:00Z"),snap)));old_fields={f.name:f for f in old.items[0].fields};self.assertEqual(set(old_fields["cvss_score"].value),{8.8,7.5})
            kev_spec=StructuredQuerySpec("cyber_kev",select_fields=("kev","date_added"),predicates=(Predicate("cve_id",PredicateOperator.EQ,"CVE-2099-0001"),))
            kev=asyncio.run(port.execute(StructuredRequest(kev_spec,SCOPE,TemporalRequest(TemporalMode.CURRENT),snap)));self.assertEqual(kev.status,ChannelStatus.OK);self.assertIs(kev.items[0].fields[0].value,True)

    def test_cyber_graph_join_uses_only_explicit_source_backed_cve_cwe_edge(self):
        with tempfile.TemporaryDirectory() as td:
            objects,meta,catalog,_rev=runtime(td)
            asyncio.run(CyberSourceLifecycle(IngestionPipeline(CVE_MANIFEST,CveListConnector((CVE_V5_FIXTURE,)),CveJsonV5Normalizer(),objects,meta)).ingest_all())
            bundle=CyberProjectionRebuilder(meta,objects).rebuild(("cve-list-v5",),"graph-manifest")
            self.assertTrue(bundle.assertions);self.assertTrue(all(a.predicate=="has_weakness" for a in bundle.assertions))
            self.assertTrue(all(dict((q.name,q.value) for q in a.qualifiers)["mapping_source"]=="CVE problemTypes.cweId" for a in bundle.assertions))
            revisions=tuple(sorted(meta.revision_uids_for_source_object("cve-list-v5","CVE-2099-0001")))
            template=TraversalTemplate("cve-cwe",(TraversalStep("has_weakness",("cve",),("cwe",)),),mapping_semantics=True)
            port=ReferenceGraphPort(catalog,SupportStore(revisions),(template,),EntityResolutionJournal(bundle.entities))
            gg=port.build(ProjectionBuildRequest("graph-cyber","graph",revisions,("graph/1",),("graph",)),bundle.entities,bundle.assertions);pub=SnapshotPublisher(catalog);pub.stage_generation(gg);manifest=pub.publish(("graph-cyber",),("graph",),created_at=NOW)
            cve=next(e for e in bundle.entities if e.entity_type=="cve")
            result=asyncio.run(port.traverse(GraphRequest((cve.entity_uid,),("has_weakness",),SCOPE,TemporalRequest(TemporalMode.CURRENT),1,10,manifest.to_ref(),template_id="cve-cwe")))
            self.assertEqual(result.status,ChannelStatus.OK);self.assertTrue(all(p.semantics=="ontology_mapping_path" for p in result.items));self.assertFalse(any("CAPEC" in " ".join(p.assertions) for p in result.items))

if __name__=="__main__":unittest.main()
