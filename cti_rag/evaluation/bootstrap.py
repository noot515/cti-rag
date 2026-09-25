"""Paired query-level bootstrap intervals with explicit inconclusive status."""
from __future__ import annotations
import random

def _quantile(values,p):
    values=sorted(float(v) for v in values)
    if not values:return None
    idx=(len(values)-1)*p;lo=int(idx);hi=min(len(values)-1,lo+1);frac=idx-lo
    return values[lo]*(1-frac)+values[hi]*frac

def paired_bootstrap(candidate,baseline,*,replicates=1000,confidence=.95,seed=0,min_pairs=30,noninferiority_margin=.01):
    candidate=tuple(float(v) for v in candidate);baseline=tuple(float(v) for v in baseline)
    if len(candidate)!=len(baseline):raise ValueError("paired bootstrap requires equal sample sizes")
    n=len(candidate)
    if n==0:return {"n":0,"delta":None,"ci_low":None,"ci_high":None,"conclusive":False,"noninferior":False,"improved":False}
    delta=sum(c-b for c,b in zip(candidate,baseline))/n
    rng=random.Random(seed);samples=[]
    for _ in range(replicates):
        total=0.0
        for _i in range(n):
            idx=rng.randrange(n);total+=candidate[idx]-baseline[idx]
        samples.append(total/n)
    alpha=(1-confidence)/2;low=_quantile(samples,alpha);high=_quantile(samples,1-alpha)
    conclusive=n>=min_pairs
    return {"n":n,"delta":delta,"ci_low":low,"ci_high":high,"conclusive":conclusive,"noninferior":bool(conclusive and low is not None and low>=-noninferiority_margin),"improved":bool(conclusive and low is not None and low>0)}
