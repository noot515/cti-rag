"""Deterministic canonical identifier parsing independent of retrieval/model code."""
from __future__ import annotations
from dataclasses import dataclass
import ipaddress,re
from typing import Callable,Optional,Tuple

@dataclass(frozen=True)
class ParsedIdentifier:
    namespace:str
    object_type:str
    canonical:str

class IdentifierRegistry:
    def __init__(self): self._parsers={}
    def register(self,namespace:str,object_type:str,parser:Callable[[str],Optional[str]]):
        if namespace in self._parsers: raise ValueError(f"identifier namespace already registered: {namespace}")
        self._parsers[namespace]=(object_type,parser); return self
    def parse_all(self,value:str,namespace:Optional[str]=None)->Tuple[ParsedIdentifier,...]:
        candidates=[]
        items=((namespace,self._parsers.get(namespace)),) if namespace else tuple(self._parsers.items())
        for ns,item in items:
            if item is None: continue
            object_type,parser=item
            canonical=parser(value)
            if canonical is not None: candidates.append(ParsedIdentifier(ns,object_type,canonical))
        return tuple(candidates)
    def parse_one(self,value:str,namespace:Optional[str]=None):
        hits=self.parse_all(value,namespace)
        return hits[0] if len(hits)==1 else None
    def namespaces(self): return tuple(sorted(self._parsers))

def _regex(pattern,upper=False,lower=False,transform=None):
    compiled=re.compile(pattern)
    def parse(value):
        v=value.strip()
        if upper:v=v.upper()
        if lower:v=v.lower()
        if not compiled.fullmatch(v): return None
        return transform(v) if transform else v
    return parse

def _cidr(value):
    try:
        text=value.strip()
        net=ipaddress.ip_network(text,strict=True)
        return net.with_prefixlen
    except ValueError:return None

def _ip(value):
    try:return ipaddress.ip_address(value.strip()).compressed
    except ValueError:return None

def default_identifier_registry():
    reg=IdentifierRegistry()
    reg.register("cve","cve",_regex(r"CVE-[0-9]{4}-[0-9]{4,}",upper=True))
    reg.register("cwe","cwe",_regex(r"CWE-[0-9]+",upper=True))
    reg.register("attack","attack-technique",_regex(r"T[0-9]{4}(?:\.[0-9]{3})?",upper=True))
    reg.register("asn","asn",_regex(r"AS[0-9]+",upper=True))
    reg.register("cidr","prefix",_cidr)
    reg.register("ip","ip-address",_ip)
    reg.register("cik","legal-entity",_regex(r"[0-9]{10}"))
    reg.register("sec-accession","sec-filing",_regex(r"[0-9]{10}-[0-9]{2}-[0-9]{6}"))
    reg.register("doi","work",_regex(r"10\.[0-9]{4,9}/\S+",lower=True))
    reg.register("rfc","rfc",_regex(r"RFC[ -]?[0-9]+",upper=True,transform=lambda v:"RFC "+re.sub(r"^RFC[ -]?","",v)))
    reg.register("isbn","edition",_regex(r"(?:97[89])?[0-9]{9}[0-9X]",upper=True))
    return reg
