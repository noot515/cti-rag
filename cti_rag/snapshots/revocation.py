"""Immediate current revocation overlay plus cleanup/invalidation coordination."""
from __future__ import annotations

class RevokedEvidenceError(PermissionError): pass

class RevocationCoordinator:
    DEFAULT_PROJECTIONS=("exact","lexical","dense","graph","structured","derived")
    def __init__(self,catalog,metadata_store=None):
        self.catalog=catalog; self.metadata_store=metadata_store
    def admit(self,target_uid,reason,projection_kinds=None):
        dependents=()
        if self.metadata_store is not None and hasattr(self.metadata_store,"dependents"):
            dependents=self.metadata_store.dependents(target_uid)
        event=self.catalog.admit_revocation(target_uid,reason,tuple(dependents),tuple(projection_kinds or self.DEFAULT_PROJECTIONS))
        if self.metadata_store is not None and hasattr(self.metadata_store,"add_revocation"):
            self.metadata_store.add_revocation(target_uid,reason)
        return event
    def is_revoked(self,*uids):
        return any(self.catalog.is_revoked(uid) for uid in uids if uid)

def candidate_is_revoked(catalog,candidate):
    uids=[]
    for name in ("passage_uid","revision_uid","entity_uid","path_uid","result_uid"):
        value=getattr(candidate,name,None)
        if value:uids.append(value)
    uids.extend(getattr(candidate,"revision_uids",()) or ())
    return any(catalog.is_revoked(uid) for uid in uids)

def admit_candidates(catalog,candidates):
    return tuple(c for c in candidates if not candidate_is_revoked(catalog,c))

class RevocationAwareEvidenceStore:
    def __init__(self,store,catalog): self.store=store; self.catalog=catalog
    def get_revision(self,revision_uid):
        if self.catalog.is_revoked(revision_uid): return None
        return self.store.get_revision(revision_uid)
    def get_artifact(self,artifact_uid):
        if self.catalog.is_revoked(artifact_uid): return None
        artifact=self.store.get_artifact(artifact_uid)
        if artifact is not None and self.catalog.is_revoked(getattr(artifact,"revision_uid",None)): return None
        return artifact
    def get_passage(self,passage_uid):
        if self.catalog.is_revoked(passage_uid): return None
        passage=self.store.get_passage(passage_uid)
        if passage is not None and self.catalog.is_revoked(getattr(passage,"revision_uid",None)): return None
        return passage
    def resolve(self,provenance):
        if self.catalog.is_revoked(provenance.revision_uid): return None
        return self.store.resolve(provenance)
    def dependents(self,evidence_uid):
        return self.store.dependents(evidence_uid)
