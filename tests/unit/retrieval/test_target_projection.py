from packages.evidence.schema import AuthorizedEvidenceView, SnapshotRef, ObjectCandidate, ChunkCandidate, PathCandidate
from packages.retrieval.planner import project_candidate_targets, deduplicate_target_objects, PlannerError


def h(ch: str) -> str:
    return ch * 64


snap = SnapshotRef(domain="cti", scope_id="s", snapshot_id=h("9"), manifest_sha256=h("8"))


def view(uid):
    return AuthorizedEvidenceView(evidence_uid=uid, domain="cti", scope_id="s", source_instances=("fixture",))


def obj_candidate(uid, cid):
    return ObjectCandidate(candidate_id=cid, domain="cti", scope_id="s", snapshot=snap, authorized_view=view(uid), object_uid=uid)


def chunk_candidate(chunk, obj, cid):
    return ChunkCandidate(candidate_id=cid, domain="cti", scope_id="s", snapshot=snap, authorized_view=view(chunk), chunk_uid=chunk, object_uid=obj)


def path_candidate(pid, cid):
    return PathCandidate(candidate_id=cid, domain="cti", scope_id="s", snapshot=snap, authorized_view=view(pid), path_id=pid)


def test_mapping_source_cve_remains_evidence_not_answer():
    source = h("a")
    candidate = obj_candidate(source, h("1"))
    projection = project_candidate_targets(
        candidate,
        task="mapping",
        requested_target_types=("weakness",),
        object_type_by_uid={source: "vulnerability"},
        source_seed_ids=frozenset({source}),
    )
    assert projection.targets == ()


def test_mapping_target_object_is_explicit_answer():
    target = h("b")
    candidate = obj_candidate(target, h("2"))
    projection = project_candidate_targets(
        candidate,
        task="mapping",
        requested_target_types=("weakness",),
        object_type_by_uid={target: "weakness"},
    )
    assert projection.targets[0].object_uid == target


def test_chunk_targets_parent_object_not_chunk_identity():
    chunk, obj = h("c"), h("b")
    candidate = chunk_candidate(chunk, obj, h("3"))
    projection = project_candidate_targets(
        candidate,
        task="general",
        requested_target_types=(),
        object_type_by_uid={obj: "weakness"},
    )
    assert projection.projection_kind == "chunk_parent"
    assert projection.targets[0].object_uid == obj
    assert projection.targets[0].object_uid != chunk


def test_path_mapping_targets_declared_terminal_object():
    pid, target = h("d"), h("e")
    candidate = path_candidate(pid, h("4"))
    projection = project_candidate_targets(
        candidate,
        task="mapping",
        requested_target_types=("technique",),
        object_type_by_uid={target: "technique"},
        path_terminal_by_id={pid: target},
    )
    assert projection.projection_kind == "path_terminal"
    assert projection.targets[0].object_uid == target


def test_path_without_terminal_fails_instead_of_guessing():
    candidate = path_candidate(h("d"), h("5"))
    try:
        project_candidate_targets(
            candidate,
            task="mapping",
            requested_target_types=(),
            object_type_by_uid={},
        )
    except PlannerError:
        pass
    else:
        raise AssertionError("expected PlannerError")


def test_target_dedup_preserves_first_occurrence_without_equivalence_inference():
    target = h("b")
    first = obj_candidate(target, h("6"))
    second = chunk_candidate(h("c"), target, h("7"))
    p1 = project_candidate_targets(first, task="general", requested_target_types=(), object_type_by_uid={target: "weakness"})
    p2 = project_candidate_targets(second, task="general", requested_target_types=(), object_type_by_uid={target: "weakness"})
    output = deduplicate_target_objects((p1, p2))
    assert [item.object_uid for item in output] == [target]
