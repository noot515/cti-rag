"""Backend-neutral capability descriptors and channel result semantics."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple
from cti_rag.contracts import ScoreDirection, TemporalMode

class ChannelStatus(str, Enum):
    OK="ok"; EMPTY="empty"; TIMEOUT="timeout"; UNAVAILABLE="unavailable"; UNSUPPORTED="unsupported"; REJECTED="rejected"

@dataclass(frozen=True)
class BackendCapabilities:
    supported_filters: frozenset[str] = frozenset()
    temporal_modes: frozenset[TemporalMode] = frozenset({TemporalMode.CURRENT})
    snapshot_support: bool = False
    requires_snapshot: bool = False
    model_fingerprint: Optional[str] = None
    languages: Tuple[str,...] = ("und",)
    cancellation: bool = False
    pagination: bool = False
    max_batch_size: int = 1
    score_direction: ScoreDirection = ScoreDirection.UNORDERED
    def __post_init__(self):
        if self.max_batch_size <= 0: raise ValueError("max_batch_size must be positive")
        if self.requires_snapshot and not self.snapshot_support: raise ValueError("requires_snapshot implies snapshot_support")

@dataclass(frozen=True)
class ChannelResult:
    status: ChannelStatus
    items: Tuple[Any,...] = ()
    reason: Optional[str] = None
    next_cursor: Optional[str] = None
    truncated: bool = False
    def __post_init__(self):
        if self.status == ChannelStatus.OK and not self.items:
            raise ValueError("ok channel result requires items; use empty for no matches")
        if self.status != ChannelStatus.OK and self.items:
            raise ValueError("non-ok channel results must not expose items")

def missing_capabilities(cap: BackendCapabilities, required_filters=frozenset(), temporal_mode=TemporalMode.CURRENT, require_snapshot=False):
    missing=[]
    for name in sorted(set(required_filters)-set(cap.supported_filters)): missing.append(f"filter:{name}")
    if temporal_mode not in cap.temporal_modes: missing.append(f"temporal:{temporal_mode.value}")
    if (require_snapshot or cap.requires_snapshot) and not cap.snapshot_support: missing.append("snapshot")
    return tuple(missing)
