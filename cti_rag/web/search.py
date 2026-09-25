"""Policy-gated web discovery adapters. Search snippets are never evidence."""
from __future__ import annotations
import inspect
from typing import Mapping
from cti_rag.contracts import AccessLabel
from cti_rag.ports.policy import NetworkDestination
from cti_rag.ports.web import DiscoveryItem,DiscoveryResult,WebStatus

def _minimized_query(request,minimizer):
    if request.labels.access_label==AccessLabel.PUBLIC:return request.query
    if minimizer is None:raise PermissionError("non-public query terms require an explicit minimizer before remote search")
    value=str(minimizer(request.query)).strip()
    if not value:raise PermissionError("query minimizer removed all remotely exposable terms")
    return value
async def _maybe_await(value):return await value if inspect.isawaitable(value) else value

class SearXNGSearchProvider:
    def __init__(self,*,base_url,policy,requester,destination_name="searxng",query_minimizer=None):
        self.base_url=base_url.rstrip("/");self.policy=policy;self.requester=requester;self.destination_name=destination_name;self.query_minimizer=query_minimizer
    async def discover(self,request):
        try:
            self.policy.authorize_network(request.scope,request.labels,request.purpose,NetworkDestination(self.destination_name,self.base_url,True))
            query=_minimized_query(request,self.query_minimizer)
        except Exception as exc:return DiscoveryResult(WebStatus.DENIED,reason=f"policy:{type(exc).__name__}")
        try:
            payload=await _maybe_await(self.requester(self.base_url+"/search",{"q":query,"format":"json","categories":"general","safesearch":1}))
            rows=payload.get("results",()) if isinstance(payload,Mapping) else ();items=[]
            for rank,row in enumerate(rows[:request.max_results],1):
                if not isinstance(row,Mapping) or not row.get("url"):continue
                items.append(DiscoveryItem(self.destination_name,str(row["url"]),str(row.get("title","")),str(row.get("content","")),rank))
            return DiscoveryResult(WebStatus.OK,tuple(items)) if items else DiscoveryResult(WebStatus.EMPTY,reason="provider returned no discoveries")
        except Exception as exc:return DiscoveryResult(WebStatus.UNAVAILABLE,reason=f"provider:{type(exc).__name__}")

class TavilySearchProvider:
    """Wrap the repository's existing WebSearcher without importing its SDK here."""
    def __init__(self,*,legacy_searcher,policy,destination_name="tavily",query_minimizer=None):
        self.searcher=legacy_searcher;self.policy=policy;self.destination_name=destination_name;self.query_minimizer=query_minimizer
    async def discover(self,request):
        try:
            self.policy.authorize_network(request.scope,request.labels,request.purpose,NetworkDestination(self.destination_name,"https://api.tavily.com",True))
            query=_minimized_query(request,self.query_minimizer)
        except Exception as exc:return DiscoveryResult(WebStatus.DENIED,reason=f"policy:{type(exc).__name__}")
        try:
            rows=await _maybe_await(self.searcher.search(query,max_results=request.max_results));items=[]
            for rank,row in enumerate(tuple(rows)[:request.max_results],1):
                if not isinstance(row,Mapping) or not row.get("url"):continue
                items.append(DiscoveryItem(self.destination_name,str(row["url"]),str(row.get("title","")),str(row.get("content","")),rank))
            return DiscoveryResult(WebStatus.OK,tuple(items)) if items else DiscoveryResult(WebStatus.EMPTY,reason="provider returned no discoveries")
        except Exception as exc:return DiscoveryResult(WebStatus.UNAVAILABLE,reason=f"provider:{type(exc).__name__}")
