"""Deterministic claim support checks plus optional semantic judging."""
from __future__ import annotations
from decimal import Decimal,InvalidOperation
import re
from typing import Iterable
from .models import CheckStatus,ClaimAssessment,ClaimStatus,GeneratedClaim,GroundingCheck,GroundingSpan,JudgeEvaluationStatus,SemanticJudgment,SemanticStatus

_NUMBER_RE=re.compile(r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z0-9_])")
def _norm_identifier(value):return re.sub(r"\s+","",value).casefold()
def _numbers(text):
    out=[]
    for token in _NUMBER_RE.findall(text):
        try:out.append(Decimal(token.replace(",","")))
        except InvalidOperation:continue
    return tuple(out)
def _compatible_metadata(claim,evidence):
    checks=(
        ("entity",claim.entity_key,getattr(evidence,"entity_key",None)),
        ("valid_time",claim.valid_time,getattr(evidence,"valid_time",None)),
        ("edition",claim.edition_key,getattr(evidence,"edition_key",None)),
        ("source_revision",claim.source_revision,getattr(getattr(evidence,"passage",None),"revision_uid",None)),
    )
    for name,expected,actual in checks:
        if expected is not None and actual is not None and expected!=actual:return False,f"{name}_mismatch"
    return True,"compatible"
def _span_for(citation,packed):
    text=packed.display_text;start=0 if citation.start is None else citation.start;end=len(text) if citation.end is None else citation.end
    if start<0 or end>len(text) or end<=start:return None
    evidence=packed.evidence;passage=evidence.passage
    return GroundingSpan(passage.passage_uid,passage.revision_uid,start,end,text[start:end],evidence.origin_group,evidence.source_id,getattr(evidence,"unit",None),getattr(evidence,"entity_key",None),getattr(evidence,"valid_time",None),getattr(evidence,"edition_key",None))

class ClaimGrounder:
    exact_validator_fingerprint="claim-exact/1"
    def __init__(self,semantic_judge=None):self.semantic_judge=semantic_judge
    async def assess(self,claim:GeneratedClaim,packed_passages:Iterable[object])->ClaimAssessment:
        passages=tuple(packed_passages);by_uid={p.evidence.passage.passage_uid:p for p in passages};cited=[];checks=[]
        for citation in claim.citations:
            packed=by_uid.get(citation.passage_uid)
            if packed is None:
                checks.append(GroundingCheck("citation",CheckStatus.FAIL,"citation target absent from validated response",citation.passage_uid));continue
            if not getattr(packed,"citation_valid",False):
                checks.append(GroundingCheck("citation",CheckStatus.FAIL,"citation target failed canonical verification",citation.passage_uid));continue
            span=_span_for(citation,packed)
            if span is None:
                checks.append(GroundingCheck("citation",CheckStatus.FAIL,"citation span is outside packed evidence",citation.passage_uid));continue
            cited.append((span,packed.evidence));checks.append(GroundingCheck("citation",CheckStatus.PASS,"citation resolves to validated packed evidence",citation.passage_uid))
        supporting=[];conflicting=[];obligations=0;passed=0
        if claim.quoted_text is not None:
            obligations+=1;matches=[span for span,_ in cited if claim.quoted_text in span.text]
            if matches:supporting.extend(matches);passed+=1;checks.append(GroundingCheck("quote",CheckStatus.PASS,"quoted text is exact within a cited span",matches[0].passage_uid))
            else:checks.append(GroundingCheck("quote",CheckStatus.FAIL,"quoted text is not exact within any cited span"))
        for identifier in claim.identifiers:
            obligations+=1;needle=_norm_identifier(identifier);matches=[span for span,_ in cited if needle and needle in _norm_identifier(span.text)]
            if matches:supporting.extend(matches);passed+=1;checks.append(GroundingCheck("identifier",CheckStatus.PASS,f"identifier {identifier!r} found in cited span",matches[0].passage_uid))
            else:checks.append(GroundingCheck("identifier",CheckStatus.FAIL,f"identifier {identifier!r} missing from cited spans"))
        for date in claim.dates:
            obligations+=1;matches=[span for span,_ in cited if date in span.text]
            if matches:supporting.extend(matches);passed+=1;checks.append(GroundingCheck("date",CheckStatus.PASS,f"date {date!r} found in cited span",matches[0].passage_uid))
            else:checks.append(GroundingCheck("date",CheckStatus.FAIL,f"date {date!r} missing from cited spans"))
        for fact in claim.numbers:
            obligations+=1;exact_matches=[];differences=[]
            for span,evidence in cited:
                if fact.unit is not None and getattr(evidence,"unit",None) not in (None,fact.unit):
                    checks.append(GroundingCheck("numeric_unit",CheckStatus.NOT_APPLICABLE,"unit mismatch is not a direct contradiction",span.passage_uid));continue
                compatible,reason=_compatible_metadata(claim,evidence)
                if not compatible:
                    checks.append(GroundingCheck("numeric_scope",CheckStatus.NOT_APPLICABLE,f"{reason} prevents direct contradiction",span.passage_uid));continue
                values=_numbers(span.text)
                if fact.value in values:exact_matches.append(span)
                elif values:differences.append(span)
            if exact_matches:supporting.extend(exact_matches);passed+=1;checks.append(GroundingCheck("numeric",CheckStatus.PASS,f"numeric value {fact.value} is present with compatible metadata",exact_matches[0].passage_uid))
            else:checks.append(GroundingCheck("numeric",CheckStatus.FAIL,f"numeric value {fact.value} missing from compatible cited spans"));conflicting.extend(differences)
        semantic=SemanticJudgment(SemanticStatus.NOT_RUN,None,JudgeEvaluationStatus.NOT_RUN)
        if obligations==0:
            if self.semantic_judge is None or not cited:checks.append(GroundingCheck("semantic",CheckStatus.NOT_APPLICABLE,"no exact obligation and no semantic judge"))
            else:
                try:semantic=await self.semantic_judge.judge(claim,tuple(span for span,_ in cited))
                except Exception as exc:semantic=SemanticJudgment(SemanticStatus.ERROR,getattr(self.semantic_judge,"fingerprint",None),JudgeEvaluationStatus.ERROR,type(exc).__name__)
                if semantic.status==SemanticStatus.ENTAILS:supporting.extend(span for span,_ in cited)
                elif semantic.status==SemanticStatus.CONTRADICTS:conflicting.extend(span for span,_ in cited)
        if claim.numbers:
            cited_uids={span.passage_uid for span,_ in cited}
            for packed in passages:
                evidence=packed.evidence
                if evidence.passage.passage_uid in cited_uids:continue
                compatible,_=_compatible_metadata(claim,evidence)
                if not compatible:continue
                full=GroundingSpan(evidence.passage.passage_uid,evidence.passage.revision_uid,0,len(packed.display_text),packed.display_text,evidence.origin_group,evidence.source_id,getattr(evidence,"unit",None),getattr(evidence,"entity_key",None),getattr(evidence,"valid_time",None),getattr(evidence,"edition_key",None))
                vals=_numbers(full.text)
                for fact in claim.numbers:
                    if fact.unit is not None and full.unit not in (None,fact.unit):continue
                    if vals and fact.value not in vals:conflicting.append(full)
        supporting=tuple({(s.passage_uid,s.start,s.end):s for s in supporting}.values());conflicting=tuple({(s.passage_uid,s.start,s.end):s for s in conflicting}.values())
        has_support=(obligations>0 and passed==obligations) or semantic.status==SemanticStatus.ENTAILS
        has_conflict=bool(conflicting) or semantic.status==SemanticStatus.CONTRADICTS
        status=ClaimStatus.MIXED if has_support and has_conflict else ClaimStatus.CONTRADICTED if has_conflict else ClaimStatus.SUPPORTED if has_support else ClaimStatus.INSUFFICIENT
        return ClaimAssessment(claim,status,supporting,conflicting,tuple(checks),tuple(sorted({s.origin_group for s in supporting})),tuple(sorted({s.origin_group for s in conflicting})),semantic)
