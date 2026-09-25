"""Pure domain specifications: schemas, identifiers, query templates, relations, fixtures."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Mapping, Optional, Tuple
@dataclass(frozen=True)
class IdentifierParser:
    namespace:str; pattern:str; uppercase:bool=False
    def parse(self,value:str)->Optional[str]:
        candidate=value.strip().upper() if self.uppercase else value.strip()
        return candidate if re.fullmatch(self.pattern,candidate) else None
@dataclass(frozen=True)
class RelationRule:
    predicate:str; subject_types:Tuple[str,...]; object_types:Tuple[str,...]; directed:bool=True
@dataclass(frozen=True)
class DomainSpec:
    name:str
    schemas:Tuple[str,...]
    identifiers:Tuple[IdentifierParser,...]
    query_templates:Tuple[Tuple[str,str],...]
    relation_rules:Tuple[RelationRule,...]
    fixtures:Tuple[Mapping[str,object],...]
    def __post_init__(self):
        if not self.name.strip() or not self.schemas: raise ValueError("domain name and schemas required")
    def parse_identifier(self,value:str):
        for parser in self.identifiers:
            parsed=parser.parse(value)
            if parsed is not None: return parser.namespace,parsed
        return None
