"""Passage-channel merge preserving each channel's raw rank metadata."""
from __future__ import annotations
from cti_rag.contracts import PassageHit,namespaced_uid

def merge_passage_hits(groups):
    merged={}
    for group in groups:
        for hit in group:
            key=(hit.passage_uid,hit.revision_uid,repr(hit.provenance.locator))
            if key not in merged:
                merged[key]=hit; continue
            prior=merged[key]
            if prior.text!=hit.text: raise ValueError("same citable passage identity has conflicting quotation text")
            scores=[]; seen=set()
            for score in prior.scores+hit.scores:
                sk=(score.channel,score.raw_rank,score.backend,score.value,score.direction.value)
                if sk not in seen:seen.add(sk);scores.append(score)
            merged[key]=PassageHit(namespaced_uid("hit","passage.channel.merge",{"passage_uid":hit.passage_uid,"channels":[s.channel for s in scores]}),hit.passage_uid,hit.revision_uid,hit.provenance,hit.text,tuple(scores))
    return tuple(sorted(merged.values(),key=lambda h:h.passage_uid))
