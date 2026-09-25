from dataclasses import dataclass
import os
def _enabled(name):
    return os.getenv(name,"0").strip().lower() in ("1","true","yes","on")
@dataclass(frozen=True)
class RetrievalFeatureFlags:
    advanced_retrieval_enabled:bool=False
    legacy_endpoints_enabled:bool=True
    web_overlay_enabled:bool=False
    @classmethod
    def from_env(cls):
        return cls(_enabled("CTI_RAG_ADVANCED_RETRIEVAL_ENABLED"),True,_enabled("CTI_RAG_WEB_OVERLAY_ENABLED"))
