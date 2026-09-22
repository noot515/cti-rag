from cti_rag.ports.capabilities import BackendCapabilities, ChannelResult, ChannelStatus
class CountingSearchPort:
    def __init__(self,capabilities:BackendCapabilities,result:ChannelResult|None=None):
        self.capabilities=capabilities; self.calls=0; self.requests=[]; self.result=result or ChannelResult(ChannelStatus.EMPTY,reason="fixture empty")
    async def search(self,request): self.calls+=1; self.requests.append(request); return self.result
class CountingModelPort:
    def __init__(self,capabilities:BackendCapabilities): self.capabilities=capabilities; self.calls=0; self.requests=[]
    async def invoke(self,request): self.calls+=1; self.requests.append(request); return {"ok":True}
class FailingPolicy:
    def authorize(self,*args,**kwargs): raise RuntimeError("policy backend failed")
    def authorize_model(self,*args,**kwargs): raise RuntimeError("policy backend failed")
