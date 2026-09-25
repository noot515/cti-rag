from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, Tuple
from cti_rag.contracts import PolicyLabels
from .capabilities import BackendCapabilities
from .policy import EffectiveScope, ProcessingDestination
class ModelOperation(str,Enum):
    EMBEDDING="embedding"; TRANSLATION="translation"; EXTRACTION="extraction"; RERANK="rerank"; GENERATION="generation"
@dataclass(frozen=True)
class ModelRequest:
    operation:ModelOperation; inputs:Tuple[Any,...]; scope:EffectiveScope; labels:PolicyLabels; destination:ProcessingDestination
class ModelPort(Protocol):
    capabilities:BackendCapabilities
    async def invoke(self,request:ModelRequest)->Any: ...
