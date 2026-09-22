from __future__ import annotations
from .spec import DomainSpec
class DomainRegistry:
    def __init__(self,specs=()):
        self._specs={}; [self.register(s) for s in specs]
    def register(self,spec:DomainSpec):
        if spec.name in self._specs: raise ValueError(f"domain already registered: {spec.name}")
        self._specs[spec.name]=spec; return spec
    def get(self,name:str)->DomainSpec:
        return self._specs[name]
    def names(self): return tuple(sorted(self._specs))
    def specs(self): return tuple(self._specs[n] for n in self.names())
def builtin_registry():
    from .cybersecurity.spec import SPEC as CYBER
    from .networking.spec import SPEC as NETWORKING
    from .quant.spec import SPEC as QUANT
    from .privacy.spec import SPEC as PRIVACY
    from .humanities.spec import SPEC as HUMANITIES
    return DomainRegistry((CYBER,NETWORKING,QUANT,PRIVACY,HUMANITIES))
