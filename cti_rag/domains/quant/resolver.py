from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
@dataclass(frozen=True)
class TickerResolution:
    security_id:str;issuer_cik:str;ticker:str;exchange:str;valid_from:str;valid_to:str|None
class TickerAliasResolver:
    def __init__(self,rows):self.rows=tuple(dict(r) for r in rows)
    def resolve(self,ticker,exchange,at_time):
        if not exchange or at_time is None:raise ValueError("ticker resolution requires exchange and time")
        if isinstance(at_time,str):at=datetime.fromisoformat(at_time.replace("Z","+00:00"))
        else:at=at_time
        if at.tzinfo is None:raise ValueError("ticker resolution time must be timezone-aware")
        point=at.astimezone(timezone.utc).isoformat().replace("+00:00","Z")
        hits=[r for r in self.rows if str(r.get("ticker","")).upper()==ticker.upper() and r.get("exchange")==exchange and r.get("alias_from")<=point and (r.get("alias_to") is None or r.get("alias_to")>point)]
        if len(hits)!=1:raise ValueError("ambiguous_or_missing_ticker_alias")
        r=hits[0];return TickerResolution(r["security_id"],r["issuer_cik"],r["ticker"],r["exchange"],r["alias_from"],r.get("alias_to"))
