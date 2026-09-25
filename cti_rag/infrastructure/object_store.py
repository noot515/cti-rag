"""Bounded immutable filesystem object store for canonical raw/normalized bytes."""
from __future__ import annotations
import hashlib,os,tempfile
from pathlib import Path
from typing import Iterable
from cti_rag.ingestion.models import ObjectRef
class ObjectStoreError(RuntimeError): pass
class FileObjectStore:
    def __init__(self,root,max_object_bytes=8*1024*1024,retention_classes=("ephemeral","standard","archive")):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True,exist_ok=True); self.max_object_bytes=int(max_object_bytes); self.retention_classes=frozenset(retention_classes)
    def _path(self,digest,retention):
        if retention not in self.retention_classes: raise ObjectStoreError("unsupported retention class")
        if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest): raise ObjectStoreError("invalid sha256 digest")
        return self.root/retention/digest[:2]/digest
    def put(self,data:bytes,retention_class="standard"):
        if len(data)>self.max_object_bytes: raise ObjectStoreError("object exceeds configured byte limit")
        digest=hashlib.sha256(data).hexdigest(); path=self._path(digest,retention_class); path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            existing=path.read_bytes()
            if hashlib.sha256(existing).hexdigest()!=digest: raise ObjectStoreError("existing immutable object failed checksum")
        else:
            fd,tmp=tempfile.mkstemp(prefix=".stage-",dir=path.parent)
            try:
                with os.fdopen(fd,"wb") as h: h.write(data); h.flush(); os.fsync(h.fileno())
                os.replace(tmp,path)
            finally:
                if os.path.exists(tmp): os.unlink(tmp)
        return ObjectRef(digest,len(data),retention_class,str(path.relative_to(self.root)))
    def exists(self,ref_or_digest,retention_class=None):
        if isinstance(ref_or_digest,ObjectRef): ref=ref_or_digest; path=self._path(ref.digest,ref.retention_class); digest=ref.digest
        else: digest=str(ref_or_digest); path=self._path(digest,retention_class or "standard")
        if not path.exists(): return False
        try:return hashlib.sha256(path.read_bytes()).hexdigest()==digest
        except OSError:return False
    def get(self,ref:ObjectRef):
        path=self._path(ref.digest,ref.retention_class); data=path.read_bytes()
        if len(data)!=ref.size_bytes or hashlib.sha256(data).hexdigest()!=ref.digest: raise ObjectStoreError("object checksum/size mismatch")
        return data
    def iter_refs(self):
        for retention in sorted(self.retention_classes):
            base=self.root/retention
            if not base.exists(): continue
            for path in base.glob("*/*"):
                if path.is_file() and len(path.name)==64:
                    yield ObjectRef(path.name,path.stat().st_size,retention,str(path.relative_to(self.root)))
    def orphan_refs(self,referenced_digests:Iterable[str]):
        referenced=set(referenced_digests); return tuple(ref for ref in self.iter_refs() if ref.digest not in referenced)
