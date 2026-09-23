import asyncio,tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path

from cti_rag.contracts import (
    AccessLabel,AssertionQualifier,EpistemicKind,EpistemicMetadata,JsonPointerLocator,PolicyLabels,ProcessingClass,
    ProvenanceRef,SourceAssertion,TemporalMode,TemporalRequest
)
from cti_rag.graph import (
    CanonicalEntity,EntityResolutionJournal,IdentityRelation,Neo4jGraphProjectionAdapter,ReferenceGraphPort,
    ResolutionDecision,TraversalStep,TraversalTemplate
)
from cti_rag.ports import EffectiveScope,GraphRequest,ProjectionBuildRequest
from cti_rag.snapshots import SnapshotCatalogStore,SnapshotPublisher

UTC=timezone.utc
NOW=datetime(2026,1,10,tzinfo=UTC)
PUBLIC=PolicyLabels("public",AccessLabel.PUBLIC,ProcessingClass.LOCAL_ONLY)
PRIVATE=PolicyLabels("public",AccessLabel.PRIVATE,ProcessingClass.LOCAL_ONLY)
SCOPE=EffectiveScope("alice","public",("cybersecurity",),(),(AccessLabel.PUBLIC,),(ProcessingClass.LOCAL_ONLY,),1)

class SupportStore:
    def __init__(self,revisions):self.revisions=set(revisions)
    def resolve(self,ref):return b"support" if ref.revision_uid in self.revisions else None
    def get_revision(self,uid):return None
    def get_artifact(self,uid):return None
    def get_passage(self,uid):return None
    def dependents(self,uid):return ()

def entity(ns,typ,ident,label=None,policy=PUBLIC,valid_from=None,valid_to=None):
    return CanonicalEntity(ns,typ,ident,label or ident,policy,"fixture",NOW,valid_from,valid_to)

def assertion(rev,left,predicate,right,policy=PUBLIC,available=NOW,valid_from=None,valid_to=None):
    return SourceAssertion(
        rev,left.ref,predicate,right.ref,(AssertionQualifier("source","fixture"),),
        (ProvenanceRef(rev,JsonPointerLocator("/mapping")),),EpistemicMetadata(EpistemicKind.SOURCE_CLAIM),
        source_id="fixture",policy=policy,available_at=available,valid_from=valid_from,valid_to=valid_to
    )

def build_graph(tmp,entities,assertions,template,support_revisions=None):
    catalog=SnapshotCatalogStore.sqlite(Path(tmp)/"catalog.db")
    resolver=EntityResolutionJournal(entities)
    port=ReferenceGraphPort(catalog,SupportStore(support_revisions or [a.revision_uid for a in assertions]),(template,),resolver)
    revs=tuple(sorted({a.revision_uid for a in assertions}))
    generation=port.build(ProjectionBuildRequest("graph-g","graph",revs,("graph-assertion/1",),("graph",)),entities,assertions)
    pub=SnapshotPublisher(catalog);pub.stage_generation(generation);manifest=pub.publish(("graph-g",),("graph",),created_at=NOW)
    return catalog,port,resolver,manifest.to_ref()

MAPPING=TraversalTemplate("cyber-ontology-mapping",(
    TraversalStep("has_weakness",("cve",),("cwe",)),
    TraversalStep("maps_to_attack_pattern",("cwe",),("capec",)),
    TraversalStep("maps_to_technique",("capec",),("attack-technique",)),
),mapping_semantics=True)

class Phase10GraphTests(unittest.TestCase):
    def test_same_name_unrelated_entities_stay_distinct_and_possible_is_not_confirmed_closure(self):
        a=entity("org","legal-entity","A","Acme");b=entity("org","legal-entity","B","Acme");c=entity("org","legal-entity","C","Acme")
        journal=EntityResolutionJournal((a,b,c))
        self.assertEqual(journal.exact("org","legal-entity","A"),(a,));self.assertEqual(len(journal.provisional("Acme","legal-entity")),3)
        p=ResolutionDecision(a.entity_uid,b.entity_uid,IdentityRelation.POSSIBLE_SAME_ENTITY,(ProvenanceRef("r1",JsonPointerLocator("/x")),),NOW)
        q=ResolutionDecision(b.entity_uid,c.entity_uid,IdentityRelation.CONFIRMED_SAME_ENTITY,(ProvenanceRef("r2",JsonPointerLocator("/x")),),NOW)
        journal.link(p);journal.link(q)
        self.assertEqual(journal.confirmed_equivalents(a.entity_uid),(a.entity_uid,))
        self.assertEqual(set(journal.confirmed_equivalents(b.entity_uid)),{b.entity_uid,c.entity_uid})
        journal.split(q.decision_uid,"later disambiguated");self.assertEqual(journal.confirmed_equivalents(b.entity_uid),(b.entity_uid,))
        journal.restore(q.decision_uid,"review restored link");self.assertEqual(len(journal.history(q.decision_uid)),3)
        security=entity("ticker","security","ACME","Acme")
        journal.add_entity(security)
        with self.assertRaises(ValueError):
            journal.link(ResolutionDecision(a.entity_uid,security.entity_uid,IdentityRelation.CONFIRMED_SAME_ENTITY,(ProvenanceRef("r3",JsonPointerLocator("/x")),),NOW))

    def test_cve_mapping_path_is_supported_and_never_labeled_observed_use(self):
        cve=entity("cve","cve","CVE-2099-0001");cwe=entity("cwe","cwe","CWE-79");capec=entity("capec","capec","CAPEC-63");attack=entity("attack","attack-technique","T9001")
        edges=(assertion("r1",cve,"has_weakness",cwe),assertion("r2",cwe,"maps_to_attack_pattern",capec),assertion("r3",capec,"maps_to_technique",attack))
        with tempfile.TemporaryDirectory() as td:
            _catalog,port,_resolver,snapshot=build_graph(td,(cve,cwe,capec,attack),edges,MAPPING)
            first=asyncio.run(port.traverse(GraphRequest((cve.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.CURRENT),2,20,snapshot,template_id=MAPPING.template_id)))
            self.assertEqual(first.status.value,"ok");self.assertTrue(first.truncated)
            two_hop=max(first.items,key=lambda x:len(x.assertion_uids))
            self.assertEqual(two_hop.relation_types,("has_weakness","maps_to_attack_pattern"));self.assertEqual(two_hop.semantics,"ontology_mapping_path")
            self.assertNotIn("observed",two_hop.semantics)
            second=asyncio.run(port.traverse(GraphRequest((capec.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.CURRENT),2,20,snapshot,template_id=MAPPING.template_id)))
            self.assertTrue(any(p.node_uids[-1]==attack.entity_uid and p.semantics=="ontology_mapping_path" for p in second.items))
            for path in first.items+second.items:
                self.assertTrue(all(port.evidence_store.resolve(ref) is not None for ref in path.provenances))

    def test_missing_support_revision_never_exposes_edge(self):
        a=entity("cve","cve","CVE-2099-0001");b=entity("cwe","cwe","CWE-79")
        edge=assertion("missing-support",a,"has_weakness",b)
        with tempfile.TemporaryDirectory() as td:
            _catalog,port,_resolver,snapshot=build_graph(td,(a,b),(edge,),MAPPING,support_revisions=())
            result=asyncio.run(port.traverse(GraphRequest((a.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.CURRENT),2,20,snapshot,template_id=MAPPING.template_id)))
            self.assertEqual(result.status.value,"empty")

    def test_historical_incompatible_edges_cannot_form_path(self):
        a=entity("cve","cve","CVE-2099-0001");b=entity("cwe","cwe","CWE-79");c=entity("capec","capec","CAPEC-63")
        jan=datetime(2025,1,1,tzinfo=UTC);feb=datetime(2025,2,1,tzinfo=UTC);mar=datetime(2025,3,1,tzinfo=UTC);apr=datetime(2025,4,1,tzinfo=UTC)
        edges=(assertion("r1",a,"has_weakness",b,available=jan,valid_from=jan,valid_to=feb),assertion("r2",b,"maps_to_attack_pattern",c,available=mar,valid_from=mar,valid_to=apr))
        with tempfile.TemporaryDirectory() as td:
            _catalog,port,_resolver,snapshot=build_graph(td,(a,b,c),edges,MAPPING)
            result=asyncio.run(port.traverse(GraphRequest((a.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.HISTORICAL_PUBLIC,cutoff_iso="2025-03-15T00:00:00Z"),2,20,snapshot,template_id=MAPPING.template_id)))
            self.assertEqual(result.status.value,"empty")

    def test_private_bridge_is_removed_before_budgets_and_counts(self):
        a=entity("cve","cve","CVE-2099-0001");private=entity("cwe","cwe","CWE-999","hidden",PRIVATE);c=entity("capec","capec","CAPEC-1");public_b=entity("cwe","cwe","CWE-79")
        edges=(assertion("r1",a,"has_weakness",private),assertion("r2",private,"maps_to_attack_pattern",c),assertion("r3",a,"has_weakness",public_b))
        with tempfile.TemporaryDirectory() as td:
            _catalog,port,_resolver,snapshot=build_graph(td,(a,private,c,public_b),edges,MAPPING)
            result=asyncio.run(port.traverse(GraphRequest((a.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.CURRENT),2,10,snapshot,template_id=MAPPING.template_id,max_degree=1,max_examined_edges=2)))
            self.assertEqual(result.status.value,"ok");self.assertEqual(len(result.items),1);self.assertEqual(result.items[0].node_uids[-1],public_b.entity_uid);self.assertFalse(result.truncated)

    def test_hub_cycle_caps_are_visible(self):
        seed=entity("cve","cve","CVE-2099-0001");neighbors=[entity("cwe","cwe",f"CWE-{i}") for i in range(1,8)]
        edges=tuple(assertion(f"r{i}",seed,"has_weakness",n) for i,n in enumerate(neighbors,1))
        with tempfile.TemporaryDirectory() as td:
            _catalog,port,_resolver,snapshot=build_graph(td,(seed,*neighbors),edges,MAPPING)
            result=asyncio.run(port.traverse(GraphRequest((seed.entity_uid,),MAPPING.relations,SCOPE,TemporalRequest(TemporalMode.CURRENT),1,20,snapshot,template_id=MAPPING.template_id,max_degree=3,max_examined_edges=3)))
            self.assertEqual(result.status.value,"ok");self.assertEqual(len(result.items),3);self.assertTrue(result.truncated);self.assertTrue(all(p.truncated for p in result.items))

    def test_neo4j_adapter_uses_only_fixed_merge_schema_and_uniqueness_constraints(self):
        calls=[]
        class Result:
            def consume(self):return self
        class Session:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def run(self,query,**kwargs):calls.append((query,kwargs));return Result()
        class Driver:
            def session(self,**kwargs):return Session()
        e=entity("cve","cve","CVE-2099-0001");f=entity("cwe","cwe","CWE-79");a=assertion("r1",e,"has_weakness",f)
        adapter=Neo4jGraphProjectionAdapter(Driver());adapter.upsert_generation("g",(e,f),(a,));adapter.upsert_generation("g",(e,f),(a,))
        queries=[q for q,_ in calls]
        self.assertTrue(any("REQUIRE e.entity_uid IS UNIQUE" in q for q in queries));self.assertTrue(any("REQUIRE a.assertion_uid IS UNIQUE" in q for q in queries))
        self.assertTrue(all("CALL " not in q.upper() for q in queries));self.assertTrue(any("MERGE (x:SourceAssertion" in q for q in queries))

if __name__=="__main__":unittest.main()
