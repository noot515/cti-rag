"""Advanced publication/indexing contracts with import-safe lazy orchestration."""
from .manifests import GenerationManifest, GenerationMember, ProjectionReceipt, ProjectionSpec, ProjectionWriter

__all__ = [
    "GenerationManifest",
    "GenerationMember",
    "ProjectionReceipt",
    "ProjectionSpec",
    "ProjectionWriter",
    "PublicationOrchestrator",
]


def __getattr__(name: str):
    if name == "PublicationOrchestrator":
        from .orchestrator import PublicationOrchestrator
        return PublicationOrchestrator
    raise AttributeError(name)
