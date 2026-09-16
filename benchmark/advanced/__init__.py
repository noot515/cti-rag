"""Advanced evaluation contracts that preserve the legacy L0 comparator."""
from .dataset import CorpusManifest, QueryRecord
from .report import BaselineRunReport, L0RunConfig, MetricResult, MetricStatus
__all__ = ["BaselineRunReport", "CorpusManifest", "L0RunConfig", "MetricResult", "MetricStatus", "QueryRecord"]
