"""Scoped persistent embedding cache; keys include security namespace and full embedding fingerprint."""
from __future__ import annotations
import json,sqlite3
from pathlib import Path
from cti_rag.contracts import sha256_hex
from .models import EmbeddingFingerprint,EmbeddingInput

class SQLiteEmbeddingCache:
    def __init__(self,path):
        self.path=str(Path(path)); self._initialize()
    def _connect(self): return sqlite3.connect(self.path)
    def _initialize(self):
        conn=self._connect()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS embedding_cache (cache_key TEXT PRIMARY KEY, fingerprint_id TEXT NOT NULL, security_namespace TEXT NOT NULL, vector_json TEXT NOT NULL)")
            conn.commit()
        finally:conn.close()
    @staticmethod
    def security_namespace(item:EmbeddingInput):
        labels=item.labels
        return f"{labels.tenant_id}:{labels.access_label.value}:{labels.processing_class.value}"
    @classmethod
    def key_for(cls,item:EmbeddingInput,fingerprint:EmbeddingFingerprint):
        return sha256_hex({
            "fingerprint":fingerprint.fingerprint_id,
            "security_namespace":cls.security_namespace(item),
            "text_digest":sha256_hex(item.text.encode("utf-8")),
            "prefix_digest":sha256_hex(item.prefix_text.encode("utf-8")),
        })
    def get(self,item,fingerprint):
        key=self.key_for(item,fingerprint); conn=self._connect()
        try:
            row=conn.execute("SELECT vector_json FROM embedding_cache WHERE cache_key=?",(key,)).fetchone()
            return None if row is None else tuple(float(v) for v in json.loads(row[0]))
        finally:conn.close()
    def put(self,item,fingerprint,vector):
        key=self.key_for(item,fingerprint); ns=self.security_namespace(item); payload=json.dumps(tuple(float(v) for v in vector),separators=(",",":"))
        conn=self._connect()
        try:
            conn.execute("INSERT OR REPLACE INTO embedding_cache (cache_key,fingerprint_id,security_namespace,vector_json) VALUES (?,?,?,?)",(key,fingerprint.fingerprint_id,ns,payload)); conn.commit()
        finally:conn.close()
    def count(self):
        conn=self._connect()
        try:return int(conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0])
        finally:conn.close()
