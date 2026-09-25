"""Neo4j projection adapter with fixed schema/queries; no arbitrary Cypher surface."""
from __future__ import annotations
from cti_rag.contracts import sha256_hex

class Neo4jGraphProjectionAdapter:
    ENTITY_CONSTRAINT="CREATE CONSTRAINT graph_entity_uid IF NOT EXISTS FOR (e:EvidenceEntity) REQUIRE e.entity_uid IS UNIQUE"
    ASSERTION_CONSTRAINT="CREATE CONSTRAINT graph_assertion_uid IF NOT EXISTS FOR (a:SourceAssertion) REQUIRE a.assertion_uid IS UNIQUE"
    GENERATION_CONSTRAINT="CREATE CONSTRAINT graph_generation_id IF NOT EXISTS FOR (g:GraphGeneration) REQUIRE g.generation_id IS UNIQUE"
    def __init__(self,driver,database=None): self.driver=driver; self.database=database
    def _session(self): return self.driver.session(database=self.database) if self.database else self.driver.session()
    def install_constraints(self):
        with self._session() as s:
            for stmt in (self.ENTITY_CONSTRAINT,self.ASSERTION_CONSTRAINT,self.GENERATION_CONSTRAINT):s.run(stmt).consume()
    def upsert_generation(self,generation_id,entities,assertions):
        self.install_constraints()
        with self._session() as s:
            s.run("MERGE (g:GraphGeneration {generation_id:$gid}) SET g.checksum=$checksum",gid=generation_id,checksum=sha256_hex({"entities":tuple(e.entity_uid for e in entities),"assertions":tuple(a.assertion_uid for a in assertions)})).consume()
            for e in entities:
                s.run("MERGE (n:EvidenceEntity {entity_uid:$uid}) SET n.namespace=$namespace,n.entity_type=$entity_type,n.identifier=$identifier,n.label=$label,n.tenant_id=$tenant,n.access_label=$access,n.source_id=$source MERGE (g:GraphGeneration {generation_id:$gid})-[:CONTAINS_ENTITY]->(n)",uid=e.entity_uid,namespace=e.namespace,entity_type=e.entity_type,identifier=e.identifier,label=e.label,tenant=e.policy.tenant_id,access=e.policy.access_label.value,source=e.source_id,gid=generation_id).consume()
            for a in assertions:
                s.run("MATCH (s:EvidenceEntity {entity_uid:$suid}),(o:EvidenceEntity {entity_uid:$ouid}) MERGE (x:SourceAssertion {assertion_uid:$aid}) SET x.predicate=$predicate,x.revision_uid=$revision,x.source_id=$source,x.tenant_id=$tenant,x.access_label=$access,x.available_at=$available,x.valid_from=$valid_from,x.valid_to=$valid_to,x.system_manifest_id=$manifest MERGE (s)-[:ASSERTS_SUBJECT]->(x) MERGE (x)-[:ASSERTS_OBJECT]->(o) MERGE (g:GraphGeneration {generation_id:$gid})-[:CONTAINS_ASSERTION]->(x)",suid=a.subject.entity_uid,ouid=a.object.entity_uid,aid=a.assertion_uid,predicate=a.predicate,revision=a.revision_uid,source=a.source_id,tenant=None if a.policy is None else a.policy.tenant_id,access=None if a.policy is None else a.policy.access_label.value,available=None if a.available_at is None else a.available_at.isoformat(),valid_from=None if a.valid_from is None else a.valid_from.isoformat(),valid_to=None if a.valid_to is None else a.valid_to.isoformat(),manifest=a.system_manifest_id,gid=generation_id).consume()
        return generation_id
    def counts(self,generation_id):
        with self._session() as s:
            row=s.run("MATCH (g:GraphGeneration {generation_id:$gid}) OPTIONAL MATCH (g)-[:CONTAINS_ENTITY]->(e) WITH g,count(DISTINCT e) AS entities OPTIONAL MATCH (g)-[:CONTAINS_ASSERTION]->(a) RETURN entities,count(DISTINCT a) AS assertions",gid=generation_id).single()
            return int(row["entities"]),int(row["assertions"])
