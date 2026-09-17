"""Response-local citation contracts for advanced evidence packing."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from packages.evidence.ids import canonical_hash
from packages.evidence.schema import CitationRecord, EvidenceModel


CitationKind = Literal["object", "chunk", "assertion", "support"]


class CitationRef(EvidenceModel):
    """Stable evidence identity plus source/field coordinates.

    Local labels are intentionally excluded from this stable reference. They are
    assigned only after a block is actually emitted in one response.
    """

    evidence_uid: str = Field(min_length=1)
    evidence_kind: CitationKind
    domain: str = Field(min_length=1)
    scope_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    object_revision_uid: str | None = None
    assertion_revision_uid: str | None = None
    field_path: str | None = None
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)
    source_uri: str | None = None
    source_instance: str | None = None
    rendered_start: int | None = Field(default=None, ge=0)
    rendered_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offsets_are_consistent(self):
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("source offsets must be supplied together")
        if self.source_start is not None and self.source_end < self.source_start:
            raise ValueError("source_end must not precede source_start")
        if (self.rendered_start is None) != (self.rendered_end is None):
            raise ValueError("rendered offsets must be supplied together")
        if self.rendered_start is not None and self.rendered_end < self.rendered_start:
            raise ValueError("rendered_end must not precede rendered_start")
        return self

    @property
    def stable_key(self) -> str:
        return canonical_hash([
            "citation-ref-v1",
            self.evidence_uid,
            self.evidence_kind,
            self.domain,
            self.scope_id,
            self.snapshot_id,
            self.object_revision_uid,
            self.assertion_revision_uid,
            self.field_path,
            self.source_start,
            self.source_end,
            self.source_uri,
            self.source_instance,
        ])


class CitationEntry(EvidenceModel):
    label: str = Field(pattern=r"^CTI-[0-9]{3,}$")
    ref: CitationRef
    emitted_start: int = Field(ge=0)
    emitted_end: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_emitted_offsets(self):
        if self.emitted_end < self.emitted_start:
            raise ValueError("citation emitted_end must not precede emitted_start")
        return self


def citation_record(entry: CitationEntry) -> CitationRecord:
    """Convert an internal local citation entry to the public result schema."""

    kwargs = dict(
        label=entry.label,
        evidence_uid=entry.ref.evidence_uid,
        domain=entry.ref.domain,
        source_uri=entry.ref.source_uri,
        emitted_start=entry.emitted_start,
        emitted_end=entry.emitted_end,
        object_revision_uid=entry.ref.object_revision_uid,
        relation_revision_uid=entry.ref.assertion_revision_uid,
    )
    # Preserve richer coordinates when the public result schema exposes them;
    # otherwise the stable CitationRef remains available in PackResult.
    fields = getattr(CitationRecord, "model_fields", {})
    optional = {
        "scope_id": entry.ref.scope_id,
        "snapshot_id": entry.ref.snapshot_id,
        "field_path": entry.ref.field_path,
        "source_start": entry.ref.source_start,
        "source_end": entry.ref.source_end,
        "citation_validity": "validated",
        "claim_support": "not_assessed",
    }
    kwargs.update({key: value for key, value in optional.items() if key in fields})
    return CitationRecord(**kwargs)


__all__ = ["CitationEntry", "CitationKind", "CitationRef", "citation_record"]
