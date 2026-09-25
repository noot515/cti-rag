"""Optional external diagnostic adapters with explicit reviewed-data exposure gates."""
from __future__ import annotations
from dataclasses import dataclass
from .models import ModelExecutionKind

@dataclass(frozen=True)
class ExternalDiagnosticRequest:
    data_fingerprint:str
    judge_fingerprint:str
    reviewed_data_exposure:bool
    model_execution:ModelExecutionKind
    def __post_init__(self):
        if not self.data_fingerprint.strip() or not self.judge_fingerprint.strip():raise ValueError("diagnostic fingerprints required")

class RAGCheckerAdapter:
    """Injected adapter only; no RAGChecker SDK dependency is imported by core evaluation."""
    name="ragchecker"
    def __init__(self,runner):self.runner=runner
    def evaluate(self,payload,request:ExternalDiagnosticRequest):
        if not request.reviewed_data_exposure:raise PermissionError("external diagnostic data exposure has not been reviewed")
        if request.model_execution!=ModelExecutionKind.REAL_MODEL:raise ValueError("external model-judged diagnostics cannot be labeled real-model quality for fake/no-model runs")
        result=self.runner(payload)
        if not isinstance(result,dict):raise ValueError("external diagnostic runner must return a mapping")
        return {"adapter":self.name,"data_fingerprint":request.data_fingerprint,"judge_fingerprint":request.judge_fingerprint,"result":result}
