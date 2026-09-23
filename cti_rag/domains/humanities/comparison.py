from __future__ import annotations
import difflib,json
from dataclasses import dataclass
from typing import Tuple
from cti_rag.contracts import locator_from_dict

@dataclass(frozen=True)
class EditionDifference:
    ordinal:int
    left_passage_id:str|None
    right_passage_id:str|None
    left_locator:object|None
    right_locator:object|None
    left_text:str|None
    right_text:str|None
    similarity:float
@dataclass(frozen=True)
class EditionComparison:
    left_edition_id:str
    right_edition_id:str
    work_id:str
    same_work:bool
    differences:Tuple[EditionDifference,...]

def _loc(d):
    if d is None:return None
    kind=d.get("kind")
    if kind=="canonical":return __import__("cti_rag.contracts",fromlist=["CanonicalPassageLocator"]).CanonicalPassageLocator(d["scheme"],d["value"])
    if kind=="tei":return __import__("cti_rag.contracts",fromlist=["TeiLocator"]).TeiLocator(d["xpath"],d.get("canonical_id"))
    if kind=="iiif":return __import__("cti_rag.contracts",fromlist=["IiifLocator"]).IiifLocator(d["canvas_id"],int(d["page"]),None if d.get("bbox") is None else tuple(d["bbox"]))
    raise ValueError("unsupported humanities locator")
def compare_editions(left_bytes:bytes,right_bytes:bytes)->EditionComparison:
    left=json.loads(left_bytes.decode());right=json.loads(right_bytes.decode())
    if left.get("kind")!="edition" or right.get("kind")!="edition":raise ValueError("edition comparison requires two normalized editions")
    lp=[p for p in left.get("passages",()) if p.get("role")=="primary_text"];rp=[p for p in right.get("passages",()) if p.get("role")=="primary_text"]
    n=max(len(lp),len(rp));diffs=[]
    for i in range(n):
        a=lp[i] if i<len(lp) else None;b=rp[i] if i<len(rp) else None
        at="" if a is None else a["normalized"];bt="" if b is None else b["normalized"]
        sim=difflib.SequenceMatcher(a=at,b=bt,autojunk=False).ratio() if a is not None and b is not None else 0.0
        if a is None or b is None or at!=bt:
            diffs.append(EditionDifference(i+1,None if a is None else a["id"],None if b is None else b["id"],None if a is None else _loc(a["locator"]),None if b is None else _loc(b["locator"]),None if a is None else a["original"],None if b is None else b["original"],sim))
    return EditionComparison(left["id"],right["id"],left.get("work_id") or "",left.get("work_id")==right.get("work_id"),tuple(diffs))
