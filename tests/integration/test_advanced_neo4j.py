from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.integration


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        pytest.skip(f"{name} is required for advanced Neo4j integration")
    return value


def _driver(uri: str, user: str, password: str):
    neo4j = pytest.importorskip("neo4j")
    return neo4j.GraphDatabase.driver(uri, auth=(user, password))


def test_advanced_neo4j_service_is_5_15_and_legacy_credentials_do_not_authenticate():
    uri = _required("ADVANCED_NEO4J_INTEGRATION_URI")
    user = _required("ADVANCED_NEO4J_USERNAME")
    password = _required("ADVANCED_NEO4J_PASSWORD")
    with _driver(uri, user, password) as driver:
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            version = session.run(
                "CALL dbms.components() YIELD versions RETURN versions[0] AS version"
            ).single()["version"]
        assert version.startswith("5.15.") or version == "5.15"

    legacy_user = os.getenv("LEGACY_NEO4J_USERNAME")
    legacy_password = os.getenv("LEGACY_NEO4J_PASSWORD")
    if not legacy_user or not legacy_password:
        pytest.skip("legacy credentials not supplied; credential-isolation release gate not run")
    with _driver(uri, legacy_user, legacy_password) as legacy:
        with pytest.raises(Exception):
            legacy.verify_connectivity()


def test_legacy_endpoint_cannot_see_advanced_probe_node():
    advanced_uri = _required("ADVANCED_NEO4J_INTEGRATION_URI")
    advanced_user = _required("ADVANCED_NEO4J_USERNAME")
    advanced_password = _required("ADVANCED_NEO4J_PASSWORD")
    legacy_uri = os.getenv("LEGACY_NEO4J_INTEGRATION_URI")
    legacy_user = os.getenv("LEGACY_NEO4J_USERNAME")
    legacy_password = os.getenv("LEGACY_NEO4J_PASSWORD")
    if not all((legacy_uri, legacy_user, legacy_password)):
        pytest.skip("legacy endpoint credentials not supplied; endpoint-isolation release gate not run")

    probe = "prompt10-isolation-probe"
    with _driver(advanced_uri, advanced_user, advanced_password) as advanced:
        with advanced.session(database="neo4j") as session:
            session.run("MERGE (n:AdvancedIsolationProbe {id:$id})", id=probe).consume()
        try:
            with _driver(legacy_uri, legacy_user, legacy_password) as legacy:
                legacy.verify_connectivity()
                with legacy.session(database="neo4j") as session:
                    count = session.run(
                        "MATCH (n:AdvancedIsolationProbe {id:$id}) RETURN count(n) AS c",
                        id=probe,
                    ).single()["c"]
                assert count == 0
        finally:
            with advanced.session(database="neo4j") as session:
                session.run(
                    "MATCH (n:AdvancedIsolationProbe {id:$id}) DETACH DELETE n", id=probe
                ).consume()
