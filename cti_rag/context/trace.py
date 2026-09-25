"""Privacy-minimized retrieval trace capture."""
from __future__ import annotations
from datetime import datetime,timezone
from cti_rag.contracts import namespaced_uid,sha256_hex
from cti_rag.planning import scope_hash
from .models import RetrievalTrace

def capture_trace(*,query,scope,plan,snapshot,reranker_fingerprint,tokenizer_fingerprint,channel_statuses,started_at,finished_at=None):
    query_digest=sha256_hex(" ".join(query.split()).encode("utf-8"))
    request_id=namespaced_uid("req","advanced.retrieval",{"query_digest":query_digest,"scope":scope_hash(scope),"snapshot":snapshot.manifest_id,"plan":plan.plan_id})
    return RetrievalTrace(
        request_id,query_digest,scope_hash(scope),plan.plan_id,plan.configuration_hash,snapshot.manifest_id,scope.policy_epoch,
        reranker_fingerprint,tokenizer_fingerprint,tuple(channel_statuses),started_at,finished_at or datetime.now(timezone.utc),
    )
