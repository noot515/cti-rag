from packages.retrieval.citations import CitationEntry, CitationRef, citation_record


def test_citation_ref_stable_identity_excludes_response_local_label():
    ref = CitationRef(
        evidence_uid="1" * 64,
        evidence_kind="chunk",
        domain="cti",
        scope_id="s",
        snapshot_id="g",
        object_revision_uid="2" * 64,
        field_path="description",
        source_start=4,
        source_end=12,
        source_uri="fixture://one",
    )
    entry = CitationEntry(
        label="CTI-001",
        ref=ref,
        emitted_start=10,
        emitted_end=18,
    )
    record = citation_record(entry)
    assert ref.stable_key == CitationRef.model_validate(ref.model_dump()).stable_key
    assert record.label == "CTI-001"
    assert record.evidence_uid == "1" * 64
    assert record.emitted_start == 10
    assert record.emitted_end == 18
    assert getattr(record, "scope_id", "s") == "s"
    assert getattr(record, "claim_support", "not_assessed") == "not_assessed"
