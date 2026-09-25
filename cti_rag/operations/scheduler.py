"""Bounded two-lane scheduler with interactive preference, fairness, and cancellation."""
from __future__ import annotations
import inspect,time
from collections import deque
from dataclasses import dataclass,field
from enum import Enum
from typing import Callable

class WorkLane(str,Enum):INTERACTIVE="interactive";INGESTION="ingestion"
class QueueFull(RuntimeError):pass

@dataclass
class CancellationToken:
    cancelled:bool=False
    def cancel(self):self.cancelled=True
    def is_set(self):return self.cancelled

@dataclass
class WorkItem:
    request_id:str
    lane:WorkLane
    factory:Callable
    token:CancellationToken=field(default_factory=CancellationToken)
    enqueued_at:float=field(default_factory=time.monotonic)
    def __post_init__(self):
        if not self.request_id.strip():raise ValueError("work item request_id required")

class BoundedScheduler:
    def __init__(self,*,interactive_capacity=32,ingestion_capacity=64,interactive_burst=4,clock=time.monotonic):
        if min(interactive_capacity,ingestion_capacity,interactive_burst)<=0:raise ValueError("queue bounds must be positive")
        self.capacities={WorkLane.INTERACTIVE:interactive_capacity,WorkLane.INGESTION:ingestion_capacity}
        self.queues={WorkLane.INTERACTIVE:deque(),WorkLane.INGESTION:deque()};self.interactive_burst=interactive_burst;self.clock=clock;self._interactive_streak=0
    def enqueue(self,item):
        q=self.queues[item.lane]
        if len(q)>=self.capacities[item.lane]:raise QueueFull(item.lane.value)
        q.append(item);return len(q)
    def cancel(self,request_id):
        count=0
        for q in self.queues.values():
            for item in q:
                if item.request_id==request_id and not item.token.cancelled:item.token.cancel();count+=1
        return count
    def sizes(self):return {lane.value:len(q) for lane,q in self.queues.items()}
    def pop_next(self):
        iq=self.queues[WorkLane.INTERACTIVE];bq=self.queues[WorkLane.INGESTION]
        while iq and iq[0].token.cancelled:iq.popleft()
        while bq and bq[0].token.cancelled:bq.popleft()
        if not iq and not bq:return None
        if iq and (not bq or self._interactive_streak<self.interactive_burst):
            self._interactive_streak+=1;return iq.popleft()
        self._interactive_streak=0;return bq.popleft()
    async def run_next(self):
        item=self.pop_next()
        if item is None:return None
        if item.token.cancelled:return {"request_id":item.request_id,"status":"cancelled"}
        started=self.clock();value=item.factory(item.token)
        if inspect.isawaitable(value):value=await value
        if item.token.cancelled:return {"request_id":item.request_id,"status":"cancelled","queue_wait_ms":(started-item.enqueued_at)*1000}
        return {"request_id":item.request_id,"status":"completed","queue_wait_ms":(started-item.enqueued_at)*1000,"result":value}
