"""Claim-level grounding contracts.

These objects intentionally separate generated claims, source spans, deterministic
checks, and optional semantic judgments. A citation pointer alone is never a
support verdict.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

class ClaimStatus(str, Enum):
    SUPPORTED="supported"; CONTRADICTED="contradicted"; MIXED="mixed"; INSUFFICIENT="insufficient"
class CheckStatus(str, Enum):
    PASS="pass"; FAIL="fail"; NOT_APPLICABLE="not_applicable"
class SemanticStatus(str, Enum):
    ENTAILS="entails"; CONTRADICTS="contradicts"; NEUTRAL="neutral"; ERROR="error"; NOT_RUN="not_run"
class JudgeEvaluationStatus(str, Enum):
    UNKNOWN="unknown"; EVALUATED="evaluated"; ERROR="error"; NOT_RUN="not_run"

@dataclass(frozen=True)
class NumericFact:
    value:Decimal
    unit:Optional[str]=None
    @classmethod
    def coerce(cls,value,unit:Optional[str]=None):
        return cls(Decimal(str(value)),None if unit is None else str(unit).strip() or None)

@dataclass(frozen=True)
class ClaimCitation:
    passage_uid:str
    start:Optional[int]=None
    end:Optional[int]=None
    def __post_init__(self):
        if not self.passage_uid.strip():raise ValueError("claim citation requires passage_uid")
        if (self.start is None)!=(self.end is None):raise ValueError("citation span requires both start and end")
        if self.start is not None and (self.start<0 or self.end<=self.start):raise ValueError("citation span requires 0 <= start < end")

@dataclass(frozen=True)
class GeneratedClaim:
    claim_id:str
    text:str
    citations:Tuple[ClaimCitation,...]
    important:bool=True
    quoted_text:Optional[str]=None
    identifiers:Tuple[str,...]=()
    dates:Tuple[str,...]=()
    numbers:Tuple[NumericFact,...]=()
    entity_key:Optional[str]=None
    valid_time:Optional[str]=None
    edition_key:Optional[str]=None
    source_revision:Optional[str]=None
    def __post_init__(self):
        if not self.claim_id.strip() or not self.text.strip():raise ValueError("generated claim requires id and text")

@dataclass(frozen=True)
class GroundingCheck:
    kind:str; status:CheckStatus; detail:str; passage_uid:Optional[str]=None

@dataclass(frozen=True)
class GroundingSpan:
    passage_uid:str
    revision_uid:str
    start:int
    end:int
    text:str
    origin_group:str
    source_id:str
    unit:Optional[str]=None
    entity_key:Optional[str]=None
    valid_time:Optional[str]=None
    edition_key:Optional[str]=None

@dataclass(frozen=True)
class SemanticJudgment:
    status:SemanticStatus
    fingerprint:Optional[str]=None
    evaluation_status:JudgeEvaluationStatus=JudgeEvaluationStatus.UNKNOWN
    detail:Optional[str]=None

@dataclass(frozen=True)
class ClaimAssessment:
    claim:GeneratedClaim
    status:ClaimStatus
    supporting_spans:Tuple[GroundingSpan,...]
    conflicting_spans:Tuple[GroundingSpan,...]
    checks:Tuple[GroundingCheck,...]
    support_origin_groups:Tuple[str,...]
    conflict_origin_groups:Tuple[str,...]
    semantic:SemanticJudgment=SemanticJudgment(SemanticStatus.NOT_RUN,None,JudgeEvaluationStatus.NOT_RUN)

@dataclass(frozen=True)
class FollowUpProposal:
    query:str
    reason:str
    depth:int=0
    max_candidates:int=12
    max_tokens:int=1200
    def __post_init__(self):
        if not self.query.strip() or not self.reason.strip():raise ValueError("follow-up proposal requires query and reason")
        if self.depth<0 or self.max_candidates<=0 or self.max_tokens<=0:raise ValueError("invalid follow-up proposal limits")

@dataclass(frozen=True)
class FollowUpOutcome:
    attempted:bool
    accepted:bool
    reason:str
    result:object|None=None
    calls_used:int=0
    tokens_reserved:int=0

@dataclass(frozen=True)
class GroundedAnswerResponse:
    answer:str
    assessments:Tuple[ClaimAssessment,...]
    unresolved:Tuple[GeneratedClaim,...]
    generation_fingerprint:Optional[str]
    judge_fingerprint:Optional[str]
    judge_evaluation_status:JudgeEvaluationStatus
    follow_up:Optional[FollowUpOutcome]=None
