"""Opt-in real Neo4j lifecycle gate. Never silently skipped into the required deterministic gate."""
import os,unittest
from cti_rag.graph import Neo4jGraphProjectionAdapter

class ActualNeo4jPhase10Tests(unittest.TestCase):
    @unittest.skipUnless(os.getenv("CTI_RAG_NEO4J_URI"),"requires CTI_RAG_NEO4J_URI")
    def test_real_constraints_are_idempotent_across_driver_reconnect(self):
        from neo4j import GraphDatabase
        uri=os.environ["CTI_RAG_NEO4J_URI"];user=os.getenv("CTI_RAG_NEO4J_USER","neo4j");password=os.environ["CTI_RAG_NEO4J_PASSWORD"]
        driver=GraphDatabase.driver(uri,auth=(user,password));Neo4jGraphProjectionAdapter(driver).install_constraints();driver.close()
        driver=GraphDatabase.driver(uri,auth=(user,password));Neo4jGraphProjectionAdapter(driver).install_constraints()
        with driver.session() as session:
            names={r["name"] for r in session.run("SHOW CONSTRAINTS YIELD name RETURN name")}
        driver.close();self.assertTrue(any("graph_entity_uid" in n for n in names));self.assertTrue(any("graph_assertion_uid" in n for n in names))

if __name__=="__main__":unittest.main()
