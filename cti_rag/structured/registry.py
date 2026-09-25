"""Server-owned dataset schemas and optional preloaded rows."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping,Tuple
from .models import DatasetSchema,StructuredValidationError

@dataclass(frozen=True)
class RegisteredDataset:
    schema:DatasetSchema
    rows:Tuple[Mapping[str,object],...]

class DatasetRegistry:
    def __init__(self):self._items={}
    def register(self,schema,rows=()):
        if schema.dataset_id in self._items:raise StructuredValidationError(f"dataset already registered: {schema.dataset_id}")
        self._items[schema.dataset_id]=RegisteredDataset(schema,tuple(dict(r) for r in rows));return self
    def get(self,dataset_id):
        try:return self._items[dataset_id]
        except KeyError as exc:raise StructuredValidationError(f"unknown dataset: {dataset_id}") from exc
    def names(self):return tuple(sorted(self._items))
