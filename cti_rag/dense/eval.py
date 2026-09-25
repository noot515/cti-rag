"""ANN recall measurement against exhaustive search over the identical eligible set."""
from __future__ import annotations
from .models import AnnRecallMeasurement

def measure_ann_recall(filter_name,ann_ids,exhaustive_ids,k,eligible_count):
    ann=tuple(ann_ids[:k]); exact=tuple(exhaustive_ids[:k]); denom=max(1,min(k,len(exact)))
    recall=len(set(ann)&set(exact))/denom
    return AnnRecallMeasurement(filter_name,k,eligible_count,ann,exact,recall)

def evaluate_ann_against_exhaustive(index,request,query_vector,ann_ids,k,filter_name):
    """Derive the exhaustive oracle from the same snapshot-selected authorized set."""
    if request.snapshot is None: raise ValueError("ANN evaluation requires pinned snapshot")
    generation_id=index.catalog.generation_for_manifest(request.snapshot.manifest_id,"dense")
    if generation_id is None: raise ValueError("snapshot has no dense generation")
    fingerprint=index._fingerprints[generation_id]
    eligible=index.eligible_records(request,generation_id)
    exhaustive=tuple(record.passage_uid for record,_score in index.exhaustive_rank(query_vector,eligible,fingerprint))
    return measure_ann_recall(filter_name,ann_ids,exhaustive,k,len(eligible))
