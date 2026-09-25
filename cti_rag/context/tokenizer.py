"""Target-tokenizer adapters; packing never estimates tokens from characters."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol,Tuple
from cti_rag.contracts import sha256_hex

class TokenizerPort(Protocol):
    name:str
    revision:str
    def encode(self,text:str)->Tuple[int,...]: ...
    def decode(self,tokens:Tuple[int,...])->str: ...

@dataclass(frozen=True)
class ContextBudget:
    total_tokens:int
    instruction_reserve:int=512
    output_reserve:int=1024
    tool_reserve:int=0
    def __post_init__(self):
        if self.total_tokens<=0 or min(self.instruction_reserve,self.output_reserve,self.tool_reserve)<0: raise ValueError("invalid token budget")
        if self.available<=0: raise ValueError("token reserves exhaust context budget")
    @property
    def available(self):return self.total_tokens-self.instruction_reserve-self.output_reserve-self.tool_reserve

class TokenizerAdapter:
    def __init__(self,tokenizer,name=None,revision="unknown"):
        self.tokenizer=tokenizer; self.name=name or getattr(tokenizer,"name_or_path",tokenizer.__class__.__name__); self.revision=revision
    def encode(self,text):
        try:values=self.tokenizer.encode(text,add_special_tokens=False)
        except TypeError:values=self.tokenizer.encode(text)
        return tuple(int(v) for v in values)
    def decode(self,tokens):
        try:return str(self.tokenizer.decode(list(tokens),skip_special_tokens=True))
        except TypeError:return str(self.tokenizer.decode(list(tokens)))
    @property
    def fingerprint(self):
        return sha256_hex({"name":self.name,"revision":self.revision})

def truncate_to_tokens(tokenizer:TokenizerPort,text:str,limit:int):
    tokens=tokenizer.encode(text)
    if len(tokens)<=limit:return text,len(tokens),False
    if limit<=0:return "",0,True
    clipped=tuple(tokens[:limit]); return tokenizer.decode(clipped),len(clipped),True
