from __future__ import annotations
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib, json, math, unicodedata
from typing import Any, Mapping, Optional
from .errors import IdentityError, ValidationError

IDENTITY_SCHEMA_VERSION="identity/1"
def _norm(s:str)->str: return unicodedata.normalize("NFC", s)
def _utc(v:datetime)->str:
    if v.tzinfo is None or v.utcoffset() is None: raise IdentityError("datetime must be timezone-aware")
    return v.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
def canonical_value(v:Any)->Any:
    if is_dataclass(v): v=asdict(v)
    if isinstance(v,Enum): return canonical_value(v.value)
    if v is None or isinstance(v,(bool,int)): return v
    if isinstance(v,float):
        if not math.isfinite(v): raise IdentityError("non-finite float")
        return 0.0 if v == 0.0 else v
    if isinstance(v,Decimal):
        if not v.is_finite(): raise IdentityError("non-finite decimal")
        sign,digits,exp=v.normalize().as_tuple(); return {"$decimal":{"sign":sign,"digits":list(digits),"exponent":exp}}
    if isinstance(v,datetime): return {"$datetime_utc":_utc(v)}
    if isinstance(v,date): return {"$date":v.isoformat()}
    if isinstance(v,bytes): return {"$bytes_sha256":hashlib.sha256(v).hexdigest(),"$bytes_length":len(v)}
    if isinstance(v,str): return _norm(v)
    if isinstance(v,Mapping):
        out={}
        for rk,rv in v.items():
            if not isinstance(rk,str): raise IdentityError("mapping keys must be strings")
            k=_norm(rk)
            if k in out: raise IdentityError("mapping keys collide after normalization")
            out[k]=canonical_value(rv)
        return out
    if isinstance(v,(list,tuple)): return [canonical_value(x) for x in v]
    if isinstance(v,(set,frozenset)):
        xs=[canonical_value(x) for x in v]; xs.sort(key=canonical_json_bytes); return xs
    raise IdentityError(f"unsupported canonical type: {type(v).__name__}")
def canonical_json_bytes(v:Any)->bytes:
    return json.dumps(canonical_value(v),ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
def sha256_hex(v:Any)->str:
    b=v if isinstance(v,bytes) else canonical_json_bytes(v); return hashlib.sha256(b).hexdigest()
def namespaced_uid(prefix:str,namespace:str,payload:Any)->str:
    if not prefix or not namespace: raise IdentityError("prefix and namespace required")
    return f"{prefix}_{sha256_hex({'identity_schema':IDENTITY_SCHEMA_VERSION,'namespace':namespace,'payload':payload})}"
@dataclass(frozen=True)
class ComponentFingerprint:
    name:str; version:str; digest:Optional[str]=None
    def __post_init__(self):
        if not self.name.strip() or not self.version.strip(): raise ValidationError("fingerprint fields required")
    def identity_material(self): return {"name":self.name,"version":self.version,"digest":self.digest}
def make_object_uid(source_namespace,upstream_object_type,stable_upstream_id): return namespaced_uid("obj","evidence.object",{"source_namespace":source_namespace,"upstream_object_type":upstream_object_type,"stable_upstream_id":stable_upstream_id})
def make_revision_uid(object_uid,upstream_version,raw_digest,identity_attributes): return namespaced_uid("rev","evidence.revision",{"object_uid":object_uid,"upstream_version":upstream_version,"raw_digest":raw_digest,"identity_attributes":identity_attributes})
def make_artifact_uid(revision_uid,parser,normalizer,schema_version,normalized_digest): return namespaced_uid("art","evidence.artifact",{"revision_uid":revision_uid,"parser":parser.identity_material(),"normalizer":normalizer.identity_material(),"schema_version":schema_version,"normalized_digest":normalized_digest})
def make_passage_uid(artifact_uid,chunker,locator,passage_digest): return namespaced_uid("psg","evidence.passage",{"artifact_uid":artifact_uid,"chunker":chunker.identity_material(),"locator":locator,"passage_digest":passage_digest})
def make_representation_uid(passage_uid,representation_kind,model=None,tokenizer=None,analyzer=None,prefix=None): return namespaced_uid("repr","evidence.representation",{"passage_uid":passage_uid,"representation_kind":representation_kind,"model":None if model is None else model.identity_material(),"tokenizer":None if tokenizer is None else tokenizer.identity_material(),"analyzer":None if analyzer is None else analyzer.identity_material(),"prefix":None if prefix is None else prefix.identity_material()})
def make_assertion_uid(revision_uid,endpoints,predicate,qualifiers,supporting_locators): return namespaced_uid("asn","evidence.assertion",{"revision_uid":revision_uid,"endpoints":endpoints,"predicate":predicate,"qualifiers":qualifiers,"supporting_locators":supporting_locators})
