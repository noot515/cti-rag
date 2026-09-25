from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from enum import Enum
from typing import Optional,Tuple
from cti_rag.contracts import EntityRef,PolicyLabels,ProvenanceRef,SourceAssertion,make_entity_uid,namespaced_uid

@dataclass(frozen=True)
class CanonicalEntity:
    namespace:str; entity_type:str; identifier:str; label:str; policy:PolicyLabels; source_id:str
    available_at:Optional[datetime]=None; valid_from:Optional[datetime]=None; valid_to:Optional[datetime]=None
    system_manifest_id:Optional[str]=None; entity_uid:Optional[str]=None
    def __post_init__(self):
        if not all(v.strip() for v in (self.namespace,self.entity_type,self.identifier,self.label,self.source_id)): raise ValueError("entity fields required")
        expected=make_entity_uid(self.namespace,self.entity_type,self.identifier)
        if self.entity_uid is None: object.__setattr__(self,"entity_uid",expected)
        elif self.entity_uid!=expected: raise ValueError("entity_uid mismatch")
    @property
    def ref(self): return EntityRef(self.namespace,self.identifier,self.entity_type,self.entity_uid)

class IdentityRelation(str,Enum):
    CONFIRMED_SAME_ENTITY="confirmed_same_entity"; POSSIBLE_SAME_ENTITY="possible_same_entity"; ALIAS_OF="alias_of"

@dataclass(frozen=True)
class ResolutionDecision:
    left_uid:str; right_uid:str; relation:IdentityRelation; support:Tuple[ProvenanceRef,...]; recorded_at:datetime
    decision_uid:Optional[str]=None
    def __post_init__(self):
        if self.left_uid==self.right_uid: raise ValueError("identity decision requires distinct entities")
        if not self.support: raise ValueError("identity decision requires support")
        if self.recorded_at.tzinfo is None: raise ValueError("resolution timestamp must be timezone-aware")
        expected=namespaced_uid("res","graph.identity",{"left":self.left_uid,"right":self.right_uid,"relation":self.relation.value,"support":tuple((s.revision_uid,repr(s.locator)) for s in self.support),"recorded_at":self.recorded_at})
        if self.decision_uid is None: object.__setattr__(self,"decision_uid",expected)
        elif self.decision_uid!=expected: raise ValueError("decision_uid mismatch")

@dataclass(frozen=True)
class ResolutionEvent:
    decision_uid:str; action:str; reason:str; recorded_at:datetime

@dataclass(frozen=True)
class TraversalStep:
    predicate:str; subject_types:Tuple[str,...]; object_types:Tuple[str,...]; direction:str="out"
    def __post_init__(self):
        if self.direction not in ("out","in","either"): raise ValueError("unsupported graph direction")

@dataclass(frozen=True)
class TraversalTemplate:
    template_id:str; steps:Tuple[TraversalStep,...]; mapping_semantics:bool=False
    def __post_init__(self):
        if not self.template_id.strip() or not self.steps: raise ValueError("traversal template requires id and steps")
    @property
    def relations(self): return tuple(dict.fromkeys(s.predicate for s in self.steps))
