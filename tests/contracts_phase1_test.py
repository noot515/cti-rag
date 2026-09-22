import unittest
from datetime import date, datetime, timezone

from cti_rag.contracts import (
    AccessLabel, ArtifactType, AvailabilityBasis, CanonicalPassageLocator,
    CharacterSpanLocator, ComponentFingerprint, EntityRef, EpistemicKind,
    EpistemicMetadata, HistoricalDate, HistoricalPrecision, IdentityAttribute,
    IndexedRepresentation, JsonPointerLocator, NormalizedArtifact,
    ObservedRevision, PageLocator, Passage, PassageHit, PolicyLabels,
    ProcessingClass, ProvenanceRef, RepresentationKind, RetrievalObservation,
    SourceObject, TemporalMetadata, UnknownDiscriminatorError, ValidationError,
    candidate_from_dict, canonical_json_bytes, locator_from_dict, merge_candidates,
    sha256_hex,
)

UTC = timezone.utc


def temporal():
    return TemporalMetadata(
        first_observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        recorded_from=datetime(2026, 1, 1, tzinfo=UTC),
        available_at=datetime(2025, 12, 31, tzinfo=UTC),
        available_at_basis=AvailabilityBasis.SOURCE_PUBLISHED,
    )


class ContractTests(unittest.TestCase):
    def test_canonical_mapping_order_and_unicode_are_stable(self):
        a = {"b": None, "a": "e\u0301"}
        b = {"a": "é", "b": None}
        self.assertEqual(canonical_json_bytes(a), canonical_json_bytes(b))

    def test_delimiter_ambiguity_does_not_collide(self):
        one = sha256_hex({"left": "a:b", "right": "c"})
        two = sha256_hex({"left": "a", "right": "b:c"})
        self.assertNotEqual(one, two)

    def test_source_object_identity_is_stable(self):
        labels = PolicyLabels("public", AccessLabel.PUBLIC, ProcessingClass.LOCAL_ONLY)
        a = SourceObject("nvd", "cve", "CVE-2026-0001", labels)
        b = SourceObject("nvd", "cve", "CVE-2026-0001", labels)
        self.assertEqual(a.object_uid, b.object_uid)

    def test_changed_content_creates_new_revision_and_old_revision_stays_addressable(self):
        labels = PolicyLabels("public", AccessLabel.PUBLIC, ProcessingClass.LOCAL_ONLY)
        source = SourceObject("archive", "record", "42", labels)
        old = ObservedRevision(source.object_uid, sha256_hex(b"old"), (), temporal())
        new = ObservedRevision(source.object_uid, sha256_hex(b"new"), (), temporal())
        fixture_store = {old.revision_uid: b"old", new.revision_uid: b"new"}
        self.assertNotEqual(old.revision_uid, new.revision_uid)
        self.assertEqual(fixture_store[old.revision_uid], b"old")

    def test_repeated_download_adds_observation_without_new_revision(self):
        labels = PolicyLabels("public", AccessLabel.PUBLIC, ProcessingClass.LOCAL_ONLY)
        source = SourceObject("archive", "record", "42", labels)
        rev = ObservedRevision(source.object_uid, sha256_hex(b"same"), (), temporal())
        obs = RetrievalObservation("obs-1", datetime(2026, 1, 2, tzinfo=UTC), ComponentFingerprint("connector", "1"))
        newer = rev.with_observation(obs)
        self.assertEqual(rev.revision_uid, newer.revision_uid)
        self.assertEqual(len(newer.observations), 1)

    def test_parser_and_chunker_fingerprints_affect_derived_identity(self):
        labels = PolicyLabels("public", AccessLabel.PUBLIC, ProcessingClass.LOCAL_ONLY)
        source = SourceObject("x", "doc", "1", labels)
        rev = ObservedRevision(source.object_uid, sha256_hex(b"raw"), (), temporal())
        norm = ComponentFingerprint("normalizer", "1")
        art1 = NormalizedArtifact(rev.revision_uid, ArtifactType.TEXT, sha256_hex(b"text"), ComponentFingerprint("parser", "1"), norm, "1")
        art2 = NormalizedArtifact(rev.revision_uid, ArtifactType.TEXT, sha256_hex(b"text"), ComponentFingerprint("parser", "2"), norm, "1")
        self.assertNotEqual(art1.artifact_uid, art2.artifact_uid)
        p1 = Passage(art1.artifact_uid, rev.revision_uid, CharacterSpanLocator(0, 4), "text", ComponentFingerprint("chunker", "1"), EpistemicMetadata(EpistemicKind.SOURCE_CLAIM))
        p2 = Passage(art1.artifact_uid, rev.revision_uid, CharacterSpanLocator(0, 4), "text", ComponentFingerprint("chunker", "2"), EpistemicMetadata(EpistemicKind.SOURCE_CLAIM))
        self.assertNotEqual(p1.passage_uid, p2.passage_uid)

    def test_model_and_analyzer_affect_representation_identity(self):
        dense1 = IndexedRepresentation("p", RepresentationKind.DENSE, model=ComponentFingerprint("embed", "1"))
        dense2 = IndexedRepresentation("p", RepresentationKind.DENSE, model=ComponentFingerprint("embed", "2"))
        lex1 = IndexedRepresentation("p", RepresentationKind.LEXICAL, analyzer=ComponentFingerprint("analyzer", "1"))
        lex2 = IndexedRepresentation("p", RepresentationKind.LEXICAL, analyzer=ComponentFingerprint("analyzer", "2"))
        self.assertNotEqual(dense1.representation_uid, dense2.representation_uid)
        self.assertNotEqual(lex1.representation_uid, lex2.representation_uid)

    def test_identical_text_from_different_sources_keeps_distinct_provenance(self):
        loc = CanonicalPassageLocator("section", "1")
        a = PassageHit("hit-a", "p-a", "rev-a", ProvenanceRef("rev-a", loc), "same")
        b = PassageHit("hit-b", "p-b", "rev-b", ProvenanceRef("rev-b", loc), "same")
        merged = merge_candidates(((a,), (b,)))
        self.assertEqual(len(merged), 2)

    def test_duplicate_retrieval_attempt_same_citation_merges(self):
        loc = CharacterSpanLocator(0, 3)
        a = PassageHit("attempt-1", "p", "rev", ProvenanceRef("rev", loc), "abc")
        b = PassageHit("attempt-2", "p", "rev", ProvenanceRef("rev", loc), "abc")
        self.assertEqual(len(merge_candidates(((a,), (b,)))), 1)

    def test_invalid_timestamps_and_locators_rejected(self):
        with self.assertRaises(ValidationError):
            TemporalMetadata(datetime(2026, 1, 1), datetime(2026, 1, 1))
        with self.assertRaises(ValidationError):
            CharacterSpanLocator(5, 5)
        with self.assertRaises(ValidationError):
            JsonPointerLocator("not/a/pointer")
        with self.assertRaises(ValidationError):
            PageLocator(0)

    def test_unknown_discriminators_rejected(self):
        with self.assertRaises(UnknownDiscriminatorError):
            locator_from_dict({"kind": "future_locator"})
        with self.assertRaises(UnknownDiscriminatorError):
            candidate_from_dict({"kind": "future_candidate"})

    def test_uncertain_historical_dates_are_not_precise_instants(self):
        uncertain = HistoricalDate(date(1850, 1, 1), date(1859, 12, 31), HistoricalPrecision.APPROXIMATE, "1850s")
        self.assertNotEqual(uncertain.earliest, uncertain.latest)


if __name__ == "__main__":
    unittest.main()
