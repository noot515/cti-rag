from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

from benchmark.advanced.matched_content import compare_content
from benchmark.advanced.release_readiness import (
    compute_readiness,
    enriched_experiment,
    evaluate_ci_gate,
    quality_evidence,
    restore_retained_generation,
)
from benchmark.advanced.metrics import BootstrapInterval
from packages.evidence.snapshot import SnapshotCatalog
from packages.evidence.store import EvidenceStore
from packages.indexing.orchestrator import PublicationOrchestrator
from tests.unit.indexing._helpers import (
    FakeProjectionWriter,
    batch_and_raw,
    generation_manifest,
    snapshot_for,
)


@dataclass(frozen=True)
class _SourceRef:
    source_instance: str
    source_object_id: str
    raw_payload_sha256: str


class _Object:
    def __init__(self, *, source_instance: str, dissemination: str = "tlp:clear") -> None:
        self.uid = "direct-object"
        self.revision_uid = "direct-revision"
        self.source_refs = (
            _SourceRef(source_instance, "source-object-1", "a" * 64),
        )
        self._payload = {
            "uid": self.uid,
            "revision_uid": self.revision_uid,
            "scope_id": "direct-scope",
            "object_type": "vulnerability",
            "name": "Matched synthetic object",
            "policy": {
                "source_instances": [source_instance],
                "dissemination": [dissemination],
                "unresolved_markings": [],
                "granular_selectors": [],
            },
        }

    def model_dump(self, *, mode: str, exclude: set[str]):
        del mode
        return {key: value for key, value in self._payload.items() if key not in exclude}


class _Store:
    def __init__(self, *, dissemination: str = "tlp:clear") -> None:
        self._payload = {
            "uid": "ingested-object",
            "revision_uid": "ingested-revision",
            "scope_id": "ingested-scope",
            "object_type": "vulnerability",
            "name": "Matched synthetic object",
            "policy": {
                "source_instances": ["opencti-fixture"],
                "dissemination": [dissemination],
                "unresolved_markings": [],
                "granular_selectors": [],
            },
        }

    def get_revision(self, domain: str, scope_id: str, revision_uid: str):
        assert (domain, scope_id, revision_uid) == (
            "cti",
            "ingested-scope",
            "ingested-revision",
        )
        return {
            "payload": self._payload,
            "sources": [
                {
                    "source_instance": "opencti-fixture",
                    "source_object_id": "source-object-1",
                    "raw_sha256": "a" * 64,
                }
            ],
        }

    def get_chunk(self, *args, **kwargs):
        raise AssertionError("no chunks are expected in this focused parity fixture")


def _batch(*, dissemination: str = "tlp:clear"):
    return SimpleNamespace(
        objects=(_Object(source_instance="direct-recorded", dissemination=dissemination),),
        relations=(),
        chunks=(),
    )


def _manifest():
    return SimpleNamespace(
        domain="cti",
        scope_id="ingested-scope",
        membership=(
            SimpleNamespace(
                kind="object",
                evidence_uid="ingested-object",
                revision_uid="ingested-revision",
            ),
        ),
    )


def _release_gates(**overrides: str) -> dict[str, str]:
    gates = {
        "rollback_mechanics": "pass",
        "predecessor_correctness": "pass",
        "authorization_policy": "pass",
        "publication_recovery": "pass",
        "real_opencti": "pass",
        "real_milvus": "pass",
        "real_neo4j": "pass",
        "backend_isolation": "pass",
        "secret_handling": "pass",
        "freshness_lifecycle": "pass",
        "judged_quality": "pass",
        "deployment_authorization": "pass",
    }
    gates.update(overrides)
    return gates


def _publish(store: EvidenceStore, batch, raw, manifest) -> None:
    store.persist_batch(batch, raw_payloads=raw, snapshot=snapshot_for(manifest))
    PublicationOrchestrator.trusted(
        store,
        [
            FakeProjectionWriter("exact", store=store),
            FakeProjectionWriter("lexical", store=store),
        ],
    ).publish(manifest)


def test_content_parity_uses_provenance_mapping_not_local_uid_or_name_matching():
    result, mapping = compare_content(_batch(), _Store(), _manifest())

    assert result["status"] == "pass"
    assert mapping["mapping_rule"].startswith("kind + source_object_id + raw_sha256")
    assert mapping["entries"][0]["direct_uid"] != mapping["entries"][0]["ingested_uid"]
    assert mapping["entries"][0]["direct_source_instance"] == "direct-recorded"
    assert mapping["entries"][0]["ingested_source_instance"] == "opencti-fixture"
    assert result["transport_provenance_is_separate"] is True


def test_marking_difference_blocks_matched_content_parity():
    result, _ = compare_content(
        _batch(dissemination="tlp:clear"),
        _Store(dissemination="tlp:red"),
        _manifest(),
    )

    assert result["status"] == "fail"
    assert {item["kind"] for item in result["mismatches"]} == {"object-semantic"}


def test_enriched_opencti_result_is_never_combined_with_matched_experiment(tmp_path: Path):
    report = tmp_path / "enriched.json"
    report.write_text("{}\n", encoding="utf-8")

    missing = enriched_experiment(None)
    present = enriched_experiment(report)

    assert missing["status"] == "not_run"
    assert missing["combined_with_matched_comparison"] is False
    assert present["status"] == "reported_separately"
    assert present["combined_with_matched_comparison"] is False


def test_unavailable_judged_labels_remain_not_comparable_or_not_run():
    evidence = quality_evidence(
        SimpleNamespace(
            quality={
                "judged_labels": None,
                "bootstrap_resamples": 2000,
                "noninferiority_margin": -0.01,
                "graph_gain_lower_bound": 0.0,
            }
        )
    )

    assert evidence["matched_fixture_quality"]["status"] == "not_comparable"
    assert evidence["noninferiority_gate"] == "not_run"
    assert evidence["graph_gain_gate"] == "not_run"
    assert evidence["quality_claim_from_fixture"] is False


def test_preregistered_ci_thresholds_are_fail_closed():
    passing = BootstrapInterval(
        mean=0.01,
        lower_95=-0.009,
        upper_95=0.03,
        resamples=2000,
        seed=20260917,
        cluster_count=5,
    )
    below_margin = BootstrapInterval(
        mean=0.0,
        lower_95=-0.011,
        upper_95=0.02,
        resamples=2000,
        seed=20260917,
        cluster_count=5,
    )
    positive_graph = BootstrapInterval(
        mean=0.02,
        lower_95=0.001,
        upper_95=0.04,
        resamples=2000,
        seed=20260917,
        cluster_count=5,
    )

    assert evaluate_ci_gate(passing, kind="noninferiority") == "pass"
    assert evaluate_ci_gate(below_margin, kind="noninferiority") == "inconclusive"
    assert evaluate_ci_gate(positive_graph, kind="graph_gain") == "pass"
    assert evaluate_ci_gate(
        BootstrapInterval(0.0, 0.0, 0.01, 2000, 20260917, 5),
        kind="graph_gain",
    ) == "inconclusive"


def test_security_or_policy_failure_blocks_release_despite_perfect_retrieval():
    readiness = compute_readiness(
        matched_content="pass",
        retrieval_parity="pass",
        rollback_mechanics="pass",
        release_evidence=_release_gates(authorization_policy="fail"),
        quality_gate="pass",
        graph_gain_gate="pass",
    )

    assert readiness["overall"] == "hold"
    assert readiness["MVP-A"]["status"] == "hold"
    assert "failed:authorization_policy" in readiness["MVP-A"]["blockers"]
    assert readiness["advanced_default"] == "opt-in"


def test_backend_isolation_failure_blocks_every_milestone():
    readiness = compute_readiness(
        matched_content="pass",
        retrieval_parity="pass",
        rollback_mechanics="pass",
        release_evidence=_release_gates(backend_isolation="fail"),
        quality_gate="pass",
        graph_gain_gate="pass",
    )

    for milestone in ("MVP-A", "MVP-B", "MVP-C"):
        assert readiness[milestone]["status"] == "hold"
        assert "failed:backend_isolation" in readiness[milestone]["blockers"]


def test_restore_retained_generation_keeps_current_revocation_overlay(tmp_path: Path):
    with EvidenceStore(tmp_path / "catalog.db", tmp_path / "raw") as store:
        first_batch, first_raw = batch_and_raw()
        first = generation_manifest(first_batch)
        _publish(store, first_batch, first_raw, first)

        second_batch, second_raw = batch_and_raw(name_suffix=" v2")
        second = generation_manifest(second_batch)
        _publish(store, second_batch, second_raw, second)
        assert SnapshotCatalog(store).active_generation(
            first.domain, first.scope_id, first.corpus_id
        )["generation_id"] == second.generation_id

        old_object = first_batch.objects[0]
        store.connection.execute(
            "INSERT INTO tombstones(domain,scope_id,evidence_kind,evidence_uid,"
            "revision_uid,reason,tombstoned_at) VALUES(?,?,?,?,?,?,?)",
            (
                first.domain,
                first.scope_id,
                "object",
                old_object.uid,
                old_object.revision_uid,
                "revoked",
                "2026-09-19T00:00:00Z",
            ),
        )

        result = restore_retained_generation(
            store,
            domain=first.domain,
            scope_id=first.scope_id,
            corpus_id=first.corpus_id,
            target_generation_id=first.generation_id,
        )
        catalog = SnapshotCatalog(store)

        assert result["status"] == "pass"
        assert result["revocation_overlay_remains_live"] is True
        assert catalog.active_generation(first.domain, first.scope_id, first.corpus_id)[
            "generation_id"
        ] == first.generation_id
        assert catalog.withdrawn(
            first,
            "object",
            old_object.uid,
            old_object.revision_uid,
        ) is True


def test_compare_ingestion_import_is_safe_in_fresh_subprocess():
    root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [sys.executable, "-c", "import benchmark.advanced.compare_ingestion"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
