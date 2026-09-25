from dataclasses import dataclass
from enum import Enum
import math
from typing import Any, Mapping, Optional, Tuple, Union
from .errors import UnknownDiscriminatorError, ValidationError
class LocatorKind(str,Enum):
    CHARACTER_SPAN="character_span"; JSON_POINTER="json_pointer"; PAGE="page"; TABLE_KEY="table_key"; TEI="tei"; IIIF="iiif"; CANONICAL_PASSAGE="canonical_passage"
@dataclass(frozen=True)
class CharacterSpanLocator:
    start:int; end:int; kind:str=LocatorKind.CHARACTER_SPAN.value
    def __post_init__(self):
        if self.start<0 or self.end<=self.start: raise ValidationError("character span requires 0 <= start < end")
def _jp(p):
    if p=="": return
    if not p.startswith("/"): raise ValidationError("JSON Pointer must begin with /")
    i=0
    while i<len(p):
        if p[i]=="~":
            if i+1>=len(p) or p[i+1] not in "01": raise ValidationError("invalid JSON Pointer escape")
            i+=2
        else:i+=1
@dataclass(frozen=True)
class JsonPointerLocator:
    pointer:str; kind:str=LocatorKind.JSON_POINTER.value
    def __post_init__(self): _jp(self.pointer)
@dataclass(frozen=True)
class PageLocator:
    page:int; bbox:Optional[Tuple[float,float,float,float]]=None; kind:str=LocatorKind.PAGE.value
    def __post_init__(self):
        if self.page<1: raise ValidationError("page locators are 1-based")
        if self.bbox is not None:
            if len(self.bbox)!=4 or any(not math.isfinite(v) for v in self.bbox): raise ValidationError("invalid bbox")
@dataclass(frozen=True)
class TableKeyLocator:
    table:str; row_key:Tuple[Tuple[str,str],...]; column:Optional[str]=None; kind:str=LocatorKind.TABLE_KEY.value
    def __post_init__(self):
        if not self.table.strip() or not self.row_key: raise ValidationError("table locator requires table and row key")
@dataclass(frozen=True)
class TeiLocator:
    xpath:str; canonical_id:Optional[str]=None; kind:str=LocatorKind.TEI.value
    def __post_init__(self):
        if not self.xpath.startswith("/"): raise ValidationError("TEI xpath must be absolute")
@dataclass(frozen=True)
class IiifLocator:
    canvas_id:str; page:int; bbox:Optional[Tuple[float,float,float,float]]=None; kind:str=LocatorKind.IIIF.value
    def __post_init__(self):
        if not self.canvas_id.strip() or self.page<1: raise ValidationError("IIIF locator requires canvas_id and 1-based page")
        if self.bbox is not None:
            if len(self.bbox)!=4 or any(not math.isfinite(v) for v in self.bbox): raise ValidationError("invalid IIIF bbox")
@dataclass(frozen=True)
class CanonicalPassageLocator:
    scheme:str; value:str; kind:str=LocatorKind.CANONICAL_PASSAGE.value
    def __post_init__(self):
        if not self.scheme.strip() or not self.value.strip(): raise ValidationError("canonical passage fields required")
Locator=Union[CharacterSpanLocator,JsonPointerLocator,PageLocator,TableKeyLocator,TeiLocator,IiifLocator,CanonicalPassageLocator]
def locator_to_data(l):
    d={"kind":l.kind}
    for k,v in l.__dict__.items():
        if k!="kind": d[k]=v
    return d
def locator_from_dict(d:Mapping[str,Any]):
    k=d.get("kind")
    if k==LocatorKind.CHARACTER_SPAN.value:return CharacterSpanLocator(int(d["start"]),int(d["end"]))
    if k==LocatorKind.JSON_POINTER.value:return JsonPointerLocator(str(d["pointer"]))
    if k==LocatorKind.PAGE.value:return PageLocator(int(d["page"]),None if d.get("bbox") is None else tuple(map(float,d["bbox"])))
    if k==LocatorKind.TABLE_KEY.value:return TableKeyLocator(str(d["table"]),tuple((str(a),str(b)) for a,b in d["row_key"]),d.get("column"))
    if k==LocatorKind.TEI.value:return TeiLocator(str(d["xpath"]),d.get("canonical_id"))
    if k==LocatorKind.IIIF.value:return IiifLocator(str(d["canvas_id"]),int(d["page"]),None if d.get("bbox") is None else tuple(map(float,d["bbox"])))
    if k==LocatorKind.CANONICAL_PASSAGE.value:return CanonicalPassageLocator(str(d["scheme"]),str(d["value"]))
    raise UnknownDiscriminatorError(f"unknown locator kind: {k!r}")
@dataclass(frozen=True)
class ProvenanceRef:
    revision_uid:str; locator:Locator; source_uri:Optional[str]=None
@dataclass(frozen=True)
class Lineage:
    parents:Tuple[str,...]=(); transformation_run_id:Optional[str]=None
