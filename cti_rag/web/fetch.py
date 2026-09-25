"""Pinned-destination fetch with redirect-time SSRF checks and bounded parsing."""
from __future__ import annotations
import asyncio,http.client,ipaddress,json,multiprocessing,socket,ssl,zlib
from dataclasses import dataclass
from datetime import datetime,timezone
from html.parser import HTMLParser
from queue import Empty
from urllib.parse import urljoin,urlsplit
from cti_rag.contracts import CharacterSpanLocator,ProvenanceRef,namespaced_uid,sha256_hex
from cti_rag.ports.policy import NetworkDestination
from cti_rag.ports.web import CapturedWebEvidence,FetchResult,WebStatus

class FetchRejected(RuntimeError):pass

@dataclass(frozen=True)
class FetchLimits:
    max_redirects:int=3;max_wire_bytes:int=2_000_000;max_decompressed_bytes:int=4_000_000;max_text_chars:int=2_000_000
    connect_timeout_seconds:float=5.0;parse_timeout_seconds:float=2.0
    allowed_schemes:tuple[str,...]=("https","http");allowed_ports:tuple[int,...]=(80,443)
    allowed_content_types:tuple[str,...]=("text/plain","text/html","application/json","application/xml","text/xml")
    max_archive_depth:int=0
    def __post_init__(self):
        if min(self.max_redirects,self.max_wire_bytes,self.max_decompressed_bytes,self.max_text_chars)<0:raise ValueError("fetch limits cannot be negative")
        if self.connect_timeout_seconds<=0 or self.parse_timeout_seconds<=0:raise ValueError("fetch timeouts must be positive")

@dataclass(frozen=True)
class TransportResponse:
    status:int;headers:tuple[tuple[str,str],...];body:bytes;peer_ip:str
    def header(self,name):
        needle=name.casefold()
        for key,value in self.headers:
            if key.casefold()==needle:return value
        return None

class DirectPinnedTransport:
    """Connect only to the already-validated IP; ignore environment proxies."""
    async def request(self,url,resolved_ip,*,timeout,max_bytes):return await asyncio.to_thread(self._request,url,resolved_ip,timeout,max_bytes)
    @staticmethod
    def _request(url,resolved_ip,timeout,max_bytes):
        parts=urlsplit(url);host=parts.hostname
        if host is None:raise FetchRejected("URL has no hostname")
        port=parts.port or (443 if parts.scheme=="https" else 80)
        raw=socket.create_connection((resolved_ip,port),timeout=timeout);peer_ip=raw.getpeername()[0];sock=raw
        try:
            if parts.scheme=="https":sock=ssl.create_default_context().wrap_socket(raw,server_hostname=host)
            target=parts.path or "/"
            if parts.query:target+="?"+parts.query
            host_header=host if parts.port is None else f"{host}:{port}"
            wire=(f"GET {target} HTTP/1.1\r\nHost: {host_header}\r\nUser-Agent: cti-rag-evidence-fetch/1\r\nAccept: text/plain,text/html,application/json,application/xml,text/xml\r\nAccept-Encoding: gzip, deflate\r\nConnection: close\r\n\r\n").encode("ascii")
            sock.sendall(wire);response=http.client.HTTPResponse(sock);response.begin();chunks=[];total=0
            while True:
                chunk=response.read(min(65536,max_bytes+1-total))
                if not chunk:break
                chunks.append(chunk);total+=len(chunk)
                if total>max_bytes:raise FetchRejected("wire byte limit exceeded")
            return TransportResponse(int(response.status),tuple((str(k),str(v)) for k,v in response.getheaders()),b"".join(chunks),str(peer_ip))
        finally:
            try:sock.close()
            except Exception:pass

class _TextExtractor(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[]
    def handle_data(self,data):
        if data.strip():self.parts.append(data.strip())

def _parse_worker(queue,raw,content_type,max_chars):
    try:
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU,(1,1))
            memory=256*1024*1024
            resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
        except Exception:pass
        text=raw.decode("utf-8",errors="replace")
        if content_type=="text/html":
            parser=_TextExtractor();parser.feed(text);text="\n".join(parser.parts)
        elif content_type=="application/json":
            text=json.dumps(json.loads(text),ensure_ascii=False,sort_keys=True,separators=(",",":"))
        queue.put((True,text[:max_chars]))
    except Exception as exc:queue.put((False,type(exc).__name__))

class RestrictedParser:
    def parse(self,raw,content_type,*,timeout,max_chars):
        ctx=multiprocessing.get_context("spawn");queue=ctx.Queue(maxsize=1);process=ctx.Process(target=_parse_worker,args=(queue,raw,content_type,max_chars),daemon=True)
        process.start();process.join(timeout)
        if process.is_alive():process.terminate();process.join(0.2);raise FetchRejected("parser time limit exceeded")
        try:ok,value=queue.get(timeout=0.5)
        except Empty as exc:raise FetchRejected("parser exited without a result") from exc
        if not ok:raise FetchRejected(f"parser rejected content: {value}")
        return str(value)

def _default_resolver(host,port):
    return tuple(dict.fromkeys(str(row[4][0]) for row in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))

def _ip_allowed(value,*,allow_private=False):
    try:ip=ipaddress.ip_address(value)
    except ValueError:return False
    mapped=getattr(ip,"ipv4_mapped",None)
    if mapped is not None:ip=mapped
    if allow_private:return not (ip.is_unspecified or ip.is_multicast or ip.is_reserved)
    return not (ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_multicast or ip.is_reserved)

def _bounded_decompress(body,encoding,limit):
    if not encoding or encoding.casefold()=="identity":
        if len(body)>limit:raise FetchRejected("decompressed byte limit exceeded")
        return body
    encoding=encoding.casefold().strip()
    if encoding=="gzip":obj=zlib.decompressobj(16+zlib.MAX_WBITS)
    elif encoding=="deflate":obj=zlib.decompressobj()
    else:raise FetchRejected("unsupported content encoding")
    out=bytearray();cursor=0
    while cursor<len(body):
        chunk=body[cursor:cursor+65536];cursor+=len(chunk);remaining=limit+1-len(out)
        out.extend(obj.decompress(chunk,max(0,remaining)))
        if len(out)>limit or obj.unconsumed_tail:raise FetchRejected("decompressed byte limit exceeded")
    remaining=limit+1-len(out)
    if remaining<=0:raise FetchRejected("decompressed byte limit exceeded")
    out.extend(obj.flush(remaining))
    if len(out)>limit:raise FetchRejected("decompressed byte limit exceeded")
    return bytes(out)

class HardenedFetchPort:
    def __init__(self,*,policy,transport=None,resolver=None,parser=None,limits=FetchLimits(),destination_name="web-fetch",allow_private_networks=False,proxy_url=None):
        if proxy_url is not None:raise ValueError("proxy transport is unsupported by the direct pinned fetcher")
        self.policy=policy;self.transport=transport or DirectPinnedTransport();self.resolver=resolver or _default_resolver;self.parser=parser or RestrictedParser();self.limits=limits;self.destination_name=destination_name;self.allow_private_networks=allow_private_networks
    def _resolve_and_validate(self,url):
        parts=urlsplit(url)
        if parts.scheme not in self.limits.allowed_schemes:raise FetchRejected("URL scheme is not allowed")
        if parts.username is not None or parts.password is not None:raise FetchRejected("URL userinfo is not allowed")
        host=parts.hostname
        if not host:raise FetchRejected("URL hostname is required")
        port=parts.port or (443 if parts.scheme=="https" else 80)
        if port not in self.limits.allowed_ports:raise FetchRejected("URL port is not allowed")
        addresses=tuple(self.resolver(host,port))
        if not addresses:raise FetchRejected("DNS resolution returned no addresses")
        if any(not _ip_allowed(ip,allow_private=self.allow_private_networks) for ip in addresses):raise FetchRejected("resolved address is not allowed")
        return addresses
    async def fetch(self,request):
        current=request.url;redirects=[];fetched_at=datetime.now(timezone.utc)
        try:
            for redirect_index in range(self.limits.max_redirects+1):
                addresses=self._resolve_and_validate(current)
                self.policy.authorize_network(request.scope,request.labels,request.purpose,NetworkDestination(self.destination_name,current,True))
                selected=addresses[0]
                response=await self.transport.request(current,selected,timeout=self.limits.connect_timeout_seconds,max_bytes=self.limits.max_wire_bytes)
                if len(response.body)>self.limits.max_wire_bytes:raise FetchRejected("wire byte limit exceeded")
                if response.peer_ip not in addresses or not _ip_allowed(response.peer_ip,allow_private=self.allow_private_networks):raise FetchRejected("actual peer address differs from authorized resolution")
                if response.status in (301,302,303,307,308):
                    location=response.header("location")
                    if not location:raise FetchRejected("redirect response has no location")
                    if redirect_index>=self.limits.max_redirects:raise FetchRejected("redirect limit exceeded")
                    redirects.append(current);current=urljoin(current,location);continue
                if response.status<200 or response.status>=300:raise FetchRejected(f"unexpected HTTP status {response.status}")
                raw_type=(response.header("content-type") or "").split(";",1)[0].strip().casefold()
                if raw_type not in self.limits.allowed_content_types:raise FetchRejected("content type is not allowed")
                raw=_bounded_decompress(response.body,response.header("content-encoding"),self.limits.max_decompressed_bytes)
                text=self.parser.parse(raw,raw_type,timeout=self.limits.parse_timeout_seconds,max_chars=self.limits.max_text_chars)
                if not text:raise FetchRejected("parsed source text is empty")
                digest=sha256_hex(raw);revision_uid=namespaced_uid("rev","web.capture",{"url":current,"digest":digest});capture_id=namespaced_uid("cap","web.capture",{"requested":request.url,"revision":revision_uid,"redirects":tuple(redirects)});available=datetime.now(timezone.utc)
                evidence=CapturedWebEvidence(capture_id,revision_uid,request.url,current,raw_type,raw,text,digest,fetched_at,available,ProvenanceRef(revision_uid,CharacterSpanLocator(0,len(text)),source_uri=current),request.labels,True,tuple(redirects))
                return FetchResult(WebStatus.OK,evidence=evidence)
            raise FetchRejected("redirect processing exhausted")
        except FetchRejected as exc:return FetchResult(WebStatus.REJECTED,reason=str(exc))
        except Exception as exc:return FetchResult(WebStatus.UNAVAILABLE,reason=f"fetch:{type(exc).__name__}")
