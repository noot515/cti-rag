from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from math import fsum
from cti_rag.contracts import ProvenanceRef,StructuredField,StructuredResult,TableKeyLocator,VerificationStatus,namespaced_uid,sha256_hex
from cti_rag.ports import StructuredRequest,ChannelStatus
from cti_rag.structured import Predicate,PredicateOperator,StructuredQuerySpec

@dataclass(frozen=True)
class EventStudySpec:
    target_security_id:str
    benchmark_security_id:str
    event_date:str
    estimation_window:tuple[int,int]=(-3,-1)
    event_window:tuple[int,int]=(0,0)
    return_definition:str="simple_close_to_close"
    missing_data_rule:str="reject"
    calculation_version:str="event-study-market-model/1"
    provider:str="fixture-provider"
    currency:str="USD"
    def __post_init__(self):
        if self.estimation_window[0]>self.estimation_window[1] or self.event_window[0]>self.event_window[1]:raise ValueError("invalid event study windows")
        if self.return_definition!="simple_close_to_close" or self.missing_data_rule!="reject":raise ValueError("unsupported event study definition")

class QuantCalculationEngine:
    def __init__(self,structured_port,max_input_rows=10000):self.port=structured_port;self.max_input_rows=max_input_rows
    async def _prices(self,security_id,scope,temporal,snapshot,provider):
        spec=StructuredQuerySpec("quant_prices",select_fields=("security_id","trading_date","close","currency","calendar","timezone","adjusted","provider","source_coordinate"),
            predicates=(Predicate("security_id",PredicateOperator.EQ,security_id),Predicate("provider",PredicateOperator.EQ,provider)),order_by=(("trading_date","asc"),),presentation_limit=self.max_input_rows)
        result=await self.port.execute(StructuredRequest(spec,scope,temporal,snapshot))
        if result.status!=ChannelStatus.OK:raise ValueError(f"price_evidence_{result.status.value}")
        hit=result.items[0];fields={f.name:f.value for f in hit.fields}
        first=next(iter(fields.values()));n=len(first) if isinstance(first,tuple) else 1
        if n>=self.max_input_rows:raise ValueError("calculation_input_limit_reached")
        rows=[]
        for i in range(n):
            rows.append({k:(v[i] if isinstance(v,tuple) else v) for k,v in fields.items()})
        return rows,hit
    @staticmethod
    def _returns(rows):
        rows=sorted(rows,key=lambda r:r["trading_date"])
        if len({r["currency"] for r in rows})!=1:raise ValueError("ambiguous_price_currency")
        if len({r["calendar"] for r in rows})!=1 or len({r["timezone"] for r in rows})!=1:raise ValueError("incompatible_price_calendar_or_timezone")
        if len({bool(r["adjusted"]) for r in rows})!=1:raise ValueError("mixed_adjustment_basis")
        out=[]
        for prev,cur in zip(rows,rows[1:]):
            out.append({"trading_date":cur["trading_date"],"return":float(cur["close"])/float(prev["close"])-1.0,"currency":cur["currency"],"calendar":cur["calendar"],"timezone":cur["timezone"],"adjusted":bool(cur["adjusted"])})
        return out
    async def returns(self,security_id,scope,temporal,snapshot,provider="fixture-provider"):
        rows,hit=await self._prices(security_id,scope,temporal,snapshot,provider);rets=self._returns(rows)
        fields=(StructuredField("security_id",security_id,"str"),StructuredField("trading_dates",tuple(r["trading_date"] for r in rets),"column"),StructuredField("simple_returns",tuple(r["return"] for r in rets),"column","ratio"),StructuredField("adjusted",rets[0]["adjusted"] if rets else None,"bool"))
        calc=sha256_hex({"security":security_id,"input":hit.input_manifest,"definition":"simple_close_to_close","version":"returns/1"});uid=namespaced_uid("structured","quant.returns",{"calc":calc})
        return StructuredResult(uid,uid,hit.revision_uids,fields,hit.provenances,VerificationStatus.VERIFIED,calc,dataset_snapshot=hit.dataset_snapshot,query_spec_hash=hit.query_spec_hash,null_rules=("missing_price_reject",),temporal_mode=temporal.mode.value,input_manifest=hit.input_manifest,calculation_version="returns/1")
    async def event_study(self,spec:EventStudySpec,scope,temporal,snapshot):
        target,t_hit=await self._prices(spec.target_security_id,scope,temporal,snapshot,spec.provider);bench,b_hit=await self._prices(spec.benchmark_security_id,scope,temporal,snapshot,spec.provider)
        tr=self._returns(target);br=self._returns(bench)
        if not tr or not br:raise ValueError("insufficient_return_history")
        if {r["currency"] for r in tr}!={spec.currency} or {r["currency"] for r in br}!={spec.currency}:raise ValueError("event_study_currency_mismatch")
        if {(r["calendar"],r["timezone"]) for r in tr}!={(r["calendar"],r["timezone"]) for r in br}:raise ValueError("event_study_calendar_mismatch")
        tmap={r["trading_date"]:r for r in tr};bmap={r["trading_date"]:r for r in br};dates=sorted(set(tmap)&set(bmap))
        if spec.event_date not in dates:raise ValueError("event_date_missing")
        idx=dates.index(spec.event_date)
        def window(pair):
            a,b=pair;ids=[idx+i for i in range(a,b+1)]
            if any(i<0 or i>=len(dates) for i in ids):raise ValueError("event_window_missing_data")
            return [dates[i] for i in ids]
        estimation=window(spec.estimation_window);event=window(spec.event_window)
        xs=[bmap[d]["return"] for d in estimation];ys=[tmap[d]["return"] for d in estimation]
        mx=fsum(xs)/len(xs);my=fsum(ys)/len(ys);den=fsum((x-mx)**2 for x in xs)
        if den==0:raise ValueError("event_study_zero_benchmark_variance")
        beta=fsum((x-mx)*(y-my) for x,y in zip(xs,ys))/den;alpha=my-beta*mx
        abnormal=tuple(tmap[d]["return"]-(alpha+beta*bmap[d]["return"]) for d in event);car=fsum(abnormal)
        revs=tuple(dict.fromkeys(t_hit.revision_uids+b_hit.revision_uids));provs=tuple(dict.fromkeys(t_hit.provenances+b_hit.provenances))
        calc=sha256_hex({"spec":spec,"target_input":t_hit.input_manifest,"benchmark_input":b_hit.input_manifest,"snapshot":snapshot.manifest_id});uid=namespaced_uid("structured","quant.event-study",{"calc":calc})
        fields=(StructuredField("target_security_id",spec.target_security_id,"str"),StructuredField("benchmark_security_id",spec.benchmark_security_id,"str"),StructuredField("event_date",spec.event_date,"date"),StructuredField("estimation_window",spec.estimation_window,"tuple"),StructuredField("event_window",spec.event_window,"tuple"),StructuredField("return_definition",spec.return_definition,"str"),StructuredField("missing_data_rule",spec.missing_data_rule,"str"),StructuredField("alpha",alpha,"float","ratio"),StructuredField("beta",beta,"float","ratio"),StructuredField("abnormal_returns",abnormal,"column","ratio"),StructuredField("cumulative_abnormal_return",car,"float","ratio"),StructuredField("association_label","event-associated abnormal return; not a causal or profitability claim","str"))
        return StructuredResult(uid,uid,revs,fields,provs,VerificationStatus.VERIFIED,calc,dataset_snapshot=t_hit.dataset_snapshot,query_spec_hash=sha256_hex(spec),null_rules=("missing_data_reject",),temporal_mode=temporal.mode.value,input_manifest=sha256_hex({"target":t_hit.input_manifest,"benchmark":b_hit.input_manifest}),calculation_version=spec.calculation_version)
