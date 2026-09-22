"""ANN recall measurement against exhaustive search over the identical eligible set."""
from __future__ import annotations
from .models import AnnRecallMeasurement

def measure_ann_recall(filter_name,ann_ids,exhaustive_ids,k,eligible_count):
    ann=tuple(ann_ids[:k]); exact=tuple(exhaustive_ids[:k]); denom=max(1,min(k,len(exact)))
    recall=len(set(ann)&set(exact))/denom
    return AnnRecallMeasurement(filter_name,k,eligible_count,ann,exact,recall)
