"""Typed structured-query contracts and dataset schema registry."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any,Optional,Tuple
from cti_rag.contracts import sha256_hex

class StructuredValidationError(ValueError):pass
class PredicateOperator(str,Enum):
    EQ="eq"; NE="ne"; LT="lt"; LE="le"; GT="gt"; GE="ge"; IN="in"; BETWEEN="between"; IS_NULL="is_null"; NOT_NULL="not_null"; IP_IN_PREFIX="ip_in_prefix"
class AggregationFunction(str,Enum):
    COUNT="count"; SUM="sum"; AVG="avg"; MIN="min"; MAX="max"
class UnknownAvailabilityPolicy(str,Enum):
    REJECT="reject"; EXCLUDE="exclude"

@dataclass(frozen=True)
class FieldSchema:
    name:str
    data_type:str
    unit:Optional[str]=None
    nullable:bool=True
    def __post_init__(self):
        if not self.name.strip() or not self.data_type.strip():raise StructuredValidationError("field schema requires name and type")

@dataclass(frozen=True)
class DatasetSchema:
    dataset_id:str
    table_name:str
    fields:Tuple[FieldSchema,...]
    logical_key_fields:Tuple[str,...]
    revision_order_field:str="revision_order"
    revision_uid_field:str="revision_uid"
    availability_field:str="available_at"
    valid_from_field:str="valid_from"
    valid_to_field:str="valid_to"
    system_manifest_field:str="system_manifest_id"
    dependency_available_field:str="dependency_available_at_max"
    dependency_manifest_field:str="dependency_manifest_id"
    data_snapshot:str="fixture"
    null_rule:str="null_is_missing"
    allowed_join_keys:Tuple[str,...]=()
    def __post_init__(self):
        names={f.name for f in self.fields}
        required=set(self.logical_key_fields)|(set((self.revision_order_field,self.revision_uid_field,self.availability_field,self.valid_from_field,self.valid_to_field,self.system_manifest_field)))
        if not self.dataset_id.strip() or not self.table_name.strip() or not self.logical_key_fields:raise StructuredValidationError("dataset schema identity/key required")
        if not required.issubset(names):raise StructuredValidationError("dataset schema missing temporal/revision fields")
        if not set(self.allowed_join_keys).issubset(names):raise StructuredValidationError("join key not declared as field")
    def field(self,name):
        for item in self.fields:
            if item.name==name:return item
        raise StructuredValidationError(f"unknown field: {name}")

@dataclass(frozen=True)
class Predicate:
    field:str
    operator:PredicateOperator
    value:Any=None
    second_value:Any=None

@dataclass(frozen=True)
class JoinSpec:
    dataset_id:str
    left_field:str
    right_field:str

@dataclass(frozen=True)
class Aggregation:
    function:AggregationFunction
    field:Optional[str]
    alias:str
    unit:Optional[str]=None
    def __post_init__(self):
        if not self.alias.strip():raise StructuredValidationError("aggregation alias required")
        if self.function!=AggregationFunction.COUNT and not self.field:raise StructuredValidationError("non-count aggregation requires field")

@dataclass(frozen=True)
class StructuredQuerySpec:
    dataset_id:str
    select_fields:Tuple[str,...]=()
    predicates:Tuple[Predicate,...]=()
    joins:Tuple[JoinSpec,...]=()
    group_by:Tuple[str,...]=()
    aggregations:Tuple[Aggregation,...]=()
    order_by:Tuple[Tuple[str,str],...]=()
    presentation_limit:int=100
    valid_at_iso:Optional[str]=None
    unknown_availability_policy:UnknownAvailabilityPolicy=UnknownAvailabilityPolicy.EXCLUDE
    spec_version:str="structured-query/2"
    def __post_init__(self):
        if not self.dataset_id.strip():raise StructuredValidationError("dataset_id required")
        if self.presentation_limit<=0:raise StructuredValidationError("presentation limit must be positive")
        if len(self.joins)>2:raise StructuredValidationError("join count exceeds structured-query bound")
    @property
    def query_spec_hash(self):
        return sha256_hex(self)
