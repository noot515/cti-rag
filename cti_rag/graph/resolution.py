from __future__ import annotations
from datetime import datetime,timezone
from .models import IdentityRelation,ResolutionDecision,ResolutionEvent

class EntityResolutionJournal:
    def __init__(self,entities=()):
        self.entities={e.entity_uid:e for e in entities}; self.decisions={}; self.events=[]
    def add_entity(self,entity):
        existing=self.entities.get(entity.entity_uid)
        if existing is not None and existing!=entity: raise ValueError("canonical entity uid collision")
        self.entities[entity.entity_uid]=entity; return entity
    def exact(self,namespace,entity_type,identifier):
        hits=[e for e in self.entities.values() if e.namespace==namespace and e.entity_type==entity_type and e.identifier==identifier]
        return tuple(sorted(hits,key=lambda e:e.entity_uid))
    def provisional(self,label,entity_type=None):
        key=" ".join(label.lower().split())
        return tuple(sorted((e for e in self.entities.values() if " ".join(e.label.lower().split())==key and (entity_type is None or e.entity_type==entity_type)),key=lambda e:e.entity_uid))
    def link(self,decision:ResolutionDecision):
        if decision.left_uid not in self.entities or decision.right_uid not in self.entities: raise ValueError("identity decision references unknown entity")
        if decision.relation==IdentityRelation.CONFIRMED_SAME_ENTITY and self.entities[decision.left_uid].entity_type!=self.entities[decision.right_uid].entity_type:
            raise ValueError("confirmed identity cannot merge distinct entity types")
        self.decisions[decision.decision_uid]=decision; self.events.append(ResolutionEvent(decision.decision_uid,"link","",decision.recorded_at)); return decision
    def split(self,decision_uid,reason):
        if decision_uid not in self.decisions: raise KeyError(decision_uid)
        event=ResolutionEvent(decision_uid,"split",reason,datetime.now(timezone.utc)); self.events.append(event); return event
    def restore(self,decision_uid,reason):
        if decision_uid not in self.decisions: raise KeyError(decision_uid)
        event=ResolutionEvent(decision_uid,"restore",reason,datetime.now(timezone.utc)); self.events.append(event); return event
    def _active(self,uid):
        active=False
        for e in self.events:
            if e.decision_uid==uid: active=e.action in ("link","restore")
        return active
    def confirmed_equivalents(self,entity_uid):
        seen={entity_uid}; frontier=[entity_uid]
        while frontier:
            cur=frontier.pop()
            for uid,d in self.decisions.items():
                if not self._active(uid) or d.relation!=IdentityRelation.CONFIRMED_SAME_ENTITY: continue
                other=d.right_uid if d.left_uid==cur else d.left_uid if d.right_uid==cur else None
                if other and other not in seen: seen.add(other); frontier.append(other)
        return tuple(sorted(seen))
    def possible_links(self,entity_uid):
        return tuple(sorted((d for uid,d in self.decisions.items() if self._active(uid) and d.relation!=IdentityRelation.CONFIRMED_SAME_ENTITY and entity_uid in (d.left_uid,d.right_uid)),key=lambda d:d.decision_uid))
    def history(self,decision_uid=None):
        return tuple(e for e in self.events if decision_uid is None or e.decision_uid==decision_uid)
