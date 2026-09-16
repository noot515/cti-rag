"""CTI marking normalization without inventing a universal clearance ordering."""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import Field

from packages.evidence.schema import EvidenceModel, EvidencePolicyMetadata


class TlpLabel(str, Enum):
    CLEAR = "tlp:clear"
    GREEN = "tlp:green"
    AMBER = "tlp:amber"
    AMBER_STRICT = "tlp:amber+strict"
    RED = "tlp:red"


class GranularMarking(EvidenceModel):
    marking_ref: str = Field(min_length=1)
    selectors: tuple[str, ...]


class CtiMarking(EvidenceModel):
    marking_ref: str = Field(min_length=1)
    definition_type: str = Field(min_length=1)
    definition: str = Field(min_length=1)

    def tlp_label(self) -> TlpLabel | None:
        if self.definition_type.lower() != "tlp":
            return None
        normalized = self.definition.strip().lower().replace(" ", "")
        aliases = {
            "clear": TlpLabel.CLEAR,
            "white": TlpLabel.CLEAR,
            "green": TlpLabel.GREEN,
            "amber": TlpLabel.AMBER,
            "amber+strict": TlpLabel.AMBER_STRICT,
            "amber+strictly": TlpLabel.AMBER_STRICT,
            "red": TlpLabel.RED,
        }
        return aliases.get(normalized)


def to_policy_metadata(
    *,
    source_instances: Iterable[str],
    markings: Iterable[CtiMarking] = (),
    granular_markings: Iterable[GranularMarking] = (),
    declared_marking_refs: Iterable[str] = (),
) -> EvidencePolicyMetadata:
    markings_tuple = tuple(markings)
    granular_tuple = tuple(granular_markings)
    declared_refs = tuple(dict.fromkeys(declared_marking_refs))
    dissemination: list[str] = []
    defined_refs = {marking.marking_ref for marking in markings_tuple}
    unresolved = any(ref not in defined_refs for ref in declared_refs)
    for marking in markings_tuple:
        label = marking.tlp_label()
        if label is None:
            unresolved = True
        else:
            dissemination.append(label.value)
    return EvidencePolicyMetadata(
        source_instances=tuple(dict.fromkeys(source_instances)),
        marking_refs=tuple(dict.fromkeys((*declared_refs, *(marking.marking_ref for marking in markings_tuple)))),
        dissemination=tuple(dict.fromkeys(dissemination)),
        granular_selectors=tuple(
            selector for granular in granular_tuple for selector in granular.selectors
        ),
        unresolved_markings=unresolved,
    )
