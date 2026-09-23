from dataclasses import dataclass
import os
@dataclass(frozen=True)
class RetrievalFeatureFlags:
    advanced_retrieval_enabled:bool=False
    legacy_endpoints_enabled:bool=True
    @classmethod
    def from_env(cls):
        value=os.getenv("CTI_RAG_ADVANCED_RETRIEVAL_ENABLED","0").strip().lower()
        return cls(value in ("1","true","yes","on"),True)
