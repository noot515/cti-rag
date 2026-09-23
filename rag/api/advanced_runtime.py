"""Explicit dependency injection for the advanced retrieval API; no runtime is constructed on import."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable,Optional
from cti_rag.composition.feature_flags import RetrievalFeatureFlags

@dataclass
class AdvancedRuntimeBinding:
    service:object
    principal_resolver:Callable[[object],object]

_binding:Optional[AdvancedRuntimeBinding]=None

def configure_advanced_runtime(service,principal_resolver):
    global _binding;_binding=AdvancedRuntimeBinding(service,principal_resolver);return _binding

def clear_advanced_runtime():
    global _binding;_binding=None

def get_advanced_runtime():
    flags=RetrievalFeatureFlags.from_env()
    if not flags.advanced_retrieval_enabled:return None
    return _binding
