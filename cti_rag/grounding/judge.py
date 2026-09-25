"""Optional semantic entailment adapter over the generic ModelPort."""
from __future__ import annotations
from typing import Mapping
from cti_rag.application.guarded import authorized_model_call
from cti_rag.contracts import PolicyLabels
from cti_rag.ports import ModelOperation,ProcessingDestination
from .models import JudgeEvaluationStatus,SemanticJudgment,SemanticStatus

class ModelSemanticJudge:
    def __init__(self,*,policy,model,scope,labels:PolicyLabels,destination:ProcessingDestination=ProcessingDestination("local",False),evaluation_status:JudgeEvaluationStatus=JudgeEvaluationStatus.UNKNOWN):
        self.policy=policy;self.model=model;self.scope=scope;self.labels=labels;self.destination=destination;self.evaluation_status=evaluation_status;self.fingerprint=getattr(getattr(model,"capabilities",None),"model_fingerprint",None)
    async def judge(self,claim,spans):
        payload={"claim":claim.text,"evidence":tuple({"passage_uid":s.passage_uid,"text":s.text} for s in spans),"labels":("entails","contradicts","neutral")}
        raw=await authorized_model_call(policy=self.policy,scope=self.scope,model=self.model,operation=ModelOperation.EXTRACTION,inputs=(payload,),labels=self.labels,destination=self.destination)
        if not isinstance(raw,Mapping):return SemanticJudgment(SemanticStatus.ERROR,self.fingerprint,JudgeEvaluationStatus.ERROR,"judge returned non-mapping")
        try:status=SemanticStatus(str(raw.get("status","neutral")))
        except ValueError:return SemanticJudgment(SemanticStatus.ERROR,self.fingerprint,JudgeEvaluationStatus.ERROR,"unknown semantic status")
        return SemanticJudgment(status,self.fingerprint,self.evaluation_status,None)
