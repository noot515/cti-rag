"""Optional read-only OpenCTI source connector.

The pycti package is imported only by from_environment(). The connector exposes
only the repository's SourceConnector interface and calls documented read APIs.
"""
from __future__ import annotations
import asyncio,base64,json,os
from datetime import datetime,timezone
from cti_rag.contracts import canonical_json_bytes
from cti_rag.ports import BackendCapabilities,SourceDeletion,SourcePage,SourceRecord

class OpenCTIUnavailable(RuntimeError):pass

_OBJECT_ATTRIBUTES="""
id
standard_id
entity_type
spec_version
created_at
updated_at
revoked
objectMarking { id standard_id definition_type definition created modified }
externalReferences { edges { node { id standard_id source_name description url external_id created modified } } }
createdBy { id standard_id entity_type name }
"""
_RELATION_ATTRIBUTES="""
id
standard_id
entity_type
spec_version
created_at
updated_at
relationship_type
objectMarking { id standard_id definition_type definition created modified }
from { ... on BasicObject { id standard_id entity_type } }
to { ... on BasicObject { id standard_id entity_type } }
"""

def _encode_cursor(kind,after):
    raw=json.dumps({"kind":kind,"after":after},sort_keys=True,separators=(",",":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _decode_cursor(cursor):
    if cursor is None:return "objects",None
    try:
        padded=cursor+"="*((4-len(cursor)%4)%4);value=json.loads(base64.urlsafe_b64decode(padded).decode())
    except Exception as exc:raise ValueError("invalid OpenCTI cursor") from exc
    if type(value) is not dict or set(value)!={"kind","after"} or value["kind"] not in ("objects","relationships") or (value["after"] is not None and type(value["after"]) is not str):
        raise ValueError("invalid OpenCTI cursor")
    return value["kind"],value["after"]

def _cancelled(token):
    if token is None:return False
    for name in ("is_set","cancelled"):
        fn=getattr(token,name,None)
        if callable(fn):
            try:
                if fn():return True
            except TypeError:pass
    return False

class OpenCTIReadConnector:
    source_id="opencti-read"
    connector_fingerprint="opencti-read-connector/1"
    capabilities=BackendCapabilities(pagination=True,cancellation=True,max_batch_size=100)

    def __init__(self,client,*,page_size=50,max_retries=3,base_backoff_seconds=.05,previous_ids=(),sleeper=asyncio.sleep):
        if not 1<=int(page_size)<=100:raise ValueError("OpenCTI page_size must be between 1 and 100")
        if not 1<=int(max_retries)<=5:raise ValueError("OpenCTI max_retries must be between 1 and 5")
        if not 0<=float(base_backoff_seconds)<=2:raise ValueError("OpenCTI backoff must be between 0 and 2 seconds")
        self.client=client;self.page_size=int(page_size);self.max_retries=int(max_retries);self.base_backoff=float(base_backoff_seconds)
        self.previous_ids=frozenset(str(v) for v in previous_ids);self.sleeper=sleeper
        self._seen=set();self._full_sync=False

    @classmethod
    def from_environment(cls,*,previous_ids=()):
        try:
            import pycti
            from pycti import OpenCTIApiClient
        except ImportError as exc:raise OpenCTIUnavailable("pycti optional dependency is not installed") from exc
        if getattr(pycti,"__version__",None)!="7.260921.0":raise OpenCTIUnavailable("unsupported pycti version; expected 7.260921.0")
        url=os.getenv("OPENCTI_URL");token=os.getenv("OPENCTI_TOKEN")
        if not url or not token:raise OpenCTIUnavailable("OPENCTI_URL and OPENCTI_TOKEN are required")
        try:timeout=int(os.getenv("OPENCTI_TIMEOUT_SECONDS","15"));page_size=int(os.getenv("OPENCTI_PAGE_SIZE","50"))
        except ValueError as exc:raise OpenCTIUnavailable("invalid OpenCTI timeout/page size") from exc
        if not 1<=timeout<=30:raise OpenCTIUnavailable("OpenCTI timeout must be between 1 and 30 seconds")
        proxy=os.getenv("OPENCTI_PROXY");proxies=None if not proxy else {"http":proxy,"https":proxy}
        ca=os.getenv("OPENCTI_CA_BUNDLE");ssl_verify=ca if ca else True
        cert_path=os.getenv("OPENCTI_CLIENT_CERT");key_path=os.getenv("OPENCTI_CLIENT_KEY")
        cert=(cert_path,key_path) if cert_path and key_path else cert_path or None
        client=OpenCTIApiClient(
            url,token,ssl_verify=ssl_verify,proxies=proxies,cert=cert,
            perform_health_check=True,requests_timeout=timeout,bundle_send_to_queue=False,
            provider="ctirag/1.0",
        )
        return cls(client,page_size=page_size,previous_ids=previous_ids)

    async def _call(self,fn,deadline,cancellation_token):
        last=None
        for attempt in range(self.max_retries):
            if _cancelled(cancellation_token):raise asyncio.CancelledError()
            if deadline is not None and datetime.now(timezone.utc)>=deadline:raise TimeoutError("OpenCTI source deadline exceeded")
            try:return await asyncio.to_thread(fn)
            except Exception as exc:
                last=exc
                if attempt+1>=self.max_retries:break
                delay=min(2.0,self.base_backoff*(2**attempt))
                if deadline is not None:
                    remaining=(deadline-datetime.now(timezone.utc)).total_seconds()
                    if remaining<=delay:raise TimeoutError("OpenCTI source deadline exceeded") from exc
                await self.sleeper(delay)
        raise OpenCTIUnavailable(f"OpenCTI read failed after bounded retries: {type(last).__name__}") from last

    async def _list(self,kind,after,deadline,cancellation_token):
        entity=self.client.stix_core_object if kind=="objects" else self.client.stix_core_relationship
        attrs=_OBJECT_ATTRIBUTES if kind=="objects" else _RELATION_ATTRIBUTES
        return await self._call(lambda:entity.list(first=self.page_size,after=after,withPagination=True,customAttributes=attrs,getAll=False),deadline,cancellation_token)

    async def fetch_page(self,cursor=None,deadline=None,cancellation_token=None):
        kind,after=_decode_cursor(cursor)
        if cursor is None:self._seen.clear();self._full_sync=True
        page=await self._list(kind,after,deadline,cancellation_token)
        if type(page) is not dict or set(page)!={"entities","pagination"} or type(page["entities"]) is not list or type(page["pagination"]) is not dict:
            raise OpenCTIUnavailable("OpenCTI pagination response schema mismatch")
        info=page["pagination"];has_next=info.get("hasNextPage");end=info.get("endCursor")
        if type(has_next) is not bool or (has_next and (type(end) is not str or not end)):
            raise OpenCTIUnavailable("OpenCTI pagination metadata is invalid")
        records=[];deletions=[]
        for metadata in page["entities"]:
            if type(metadata) is not dict or not str(metadata.get("id","")).strip():raise OpenCTIUnavailable("OpenCTI entity metadata is invalid")
            stix=await self._call(lambda ident=metadata["id"]:self.client.get_stix_content(ident),deadline,cancellation_token)
            if type(stix) is not dict or not str(stix.get("id","")).strip():raise OpenCTIUnavailable("OpenCTI STIX export is invalid")
            stable=str(stix["id"]);self._seen.add(stable)
            version=str(metadata.get("updated_at") or stix.get("modified") or stix.get("created") or metadata.get("standard_id") or "unknown")
            raw=canonical_json_bytes({"opencti":metadata,"stix":stix})
            records.append(SourceRecord(stable,raw,version))
            if stix.get("revoked") is True or stix.get("x_mitre_deprecated") is True:
                deletions.append(SourceDeletion(stable,"OpenCTI imported STIX object revoked/deprecated"))
        if has_next:
            next_cursor=_encode_cursor(kind,end);exhausted=False
        elif kind=="objects":
            next_cursor=_encode_cursor("relationships",None);exhausted=False
        else:
            next_cursor=None;exhausted=True
            if self._full_sync:
                for missing in sorted(self.previous_ids-self._seen):
                    deletions.append(SourceDeletion(missing,"absent from completed OpenCTI synchronization"))
            self._full_sync=False
        unique={d.stable_upstream_id:d for d in deletions}
        return SourcePage(tuple(records),next_cursor,exhausted,tuple(unique[k] for k in sorted(unique)))
