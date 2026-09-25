"""Sanitized operational metrics and separately authorized protected traces."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
import hashlib,json,resource,time
from collections import deque

def digest_text(value):return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
_SAFE_KEYS={"candidate_count","rejection_count","cache_hit","model_tokens","queue_wait_ms","latency_ms","freshness_lag_seconds","projection_ready","projection_visible","backend_failures","status"}

@dataclass(frozen=True)
class MemorySample:
    rss_mb:float
    vram_mb:float|None
    vram_status:str

class MemoryProbe:
    def __init__(self,gpu_sampler=None):self.gpu_sampler=gpu_sampler
    def sample(self):
        usage=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss=float(usage)/(1024 if usage>1024*1024 else 1)
        if self.gpu_sampler is None:return MemorySample(rss,None,"not_available")
        value=self.gpu_sampler();return MemorySample(rss,float(value),"available")

class ConcurrentMemoryWindow:
    def __init__(self,probe=None):self.probe=probe or MemoryProbe();self.peak_rss_mb=0.0;self.peak_vram_mb=None;self.samples=0
    def record(self,active_stages):
        active=set(active_stages)
        if not {"generation","reranking"}.issubset(active):return None
        sample=self.probe.sample();self.samples+=1;self.peak_rss_mb=max(self.peak_rss_mb,sample.rss_mb)
        if sample.vram_mb is not None:self.peak_vram_mb=max(self.peak_vram_mb or 0.0,sample.vram_mb)
        return sample
    def report(self):return {"samples":self.samples,"peak_rss_mb":self.peak_rss_mb if self.samples else None,"peak_vram_mb":self.peak_vram_mb,"gpu_status":"available" if self.peak_vram_mb is not None else "not_available"}

class TelemetryRecorder:
    def __init__(self,max_events=1000,clock=time.time):
        if max_events<=0:raise ValueError("max_events must be positive")
        self.events=deque(maxlen=max_events);self.clock=clock
    def record(self,stage,*,query=None,request_id=None,fields=None):
        safe={}
        for key,value in (fields or {}).items():
            if key not in _SAFE_KEYS:continue
            if isinstance(value,(str,int,float,bool)) or value is None:safe[key]=value
        event={"ts":float(self.clock()),"stage":str(stage),"request_id":request_id,"query_digest":None if query is None else digest_text(query),"metrics":safe}
        self.events.append(event);return event
    def export_json(self):return json.dumps(list(self.events),sort_keys=True,separators=(",",":"))

class ProtectedDebugTraceStore:
    def __init__(self,max_records=100):self.records=deque(maxlen=max_records)
    def put(self,trace,*,authorized):
        if not authorized:raise PermissionError("protected debug trace access is not authorized")
        self.records.append(trace);return len(self.records)

def freshness_status(manifest,projection_generations,now=None):
    now=now or datetime.now(timezone.utc)
    lag=max(0.0,(now-manifest.created_at).total_seconds())
    statuses=tuple(sorted((g.kind,bool(g.ready),bool(g.visible),bool(g.referential_integrity)) for g in projection_generations))
    return {"manifest_id":manifest.manifest_id,"freshness_lag_seconds":lag,"projections":statuses}
