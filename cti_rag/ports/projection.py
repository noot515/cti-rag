"""Projection build contracts for immutable staged index generations."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Tuple

@dataclass(frozen=True)
class ProjectionBuildRequest:
    generation_id: str
    kind: str
    revision_uids: Tuple[str,...]
    representation_versions: Tuple[str,...] = ()
    supported_query_capabilities: Tuple[str,...] = ()
    quarantined_count: int = 0
    def __post_init__(self):
        if not self.generation_id.strip() or not self.kind.strip(): raise ValueError("projection generation identity required")
        if len(set(self.revision_uids)) != len(self.revision_uids): raise ValueError("revision_uids must be unique")
        if self.quarantined_count < 0: raise ValueError("quarantined_count cannot be negative")

class ProjectionBuilder(Protocol):
    kind: str
    def build(self, request: ProjectionBuildRequest): ...
    def validate(self, generation): ...
    def cleanup(self, generation_id: str) -> None: ...
