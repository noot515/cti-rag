from __future__ import annotations
import base64,json
from cti_rag.contracts import canonical_json_bytes,sha256_hex
from cti_rag.ports import SourceRecord
SCHEMA="network-source-snapshot/1"
def export_source_records(source_id,records):
    payload={"schema":SCHEMA,"source_id":source_id,"records":[{"record_key":r.record_key,"upstream_version":r.upstream_version,"claimed_digest":r.claimed_digest,"raw_b64":base64.b64encode(r.raw_bytes).decode()} for r in records]}
    body=canonical_json_bytes(payload);return canonical_json_bytes({"payload":payload,"sha256":sha256_hex(body)})
def import_source_records(blob):
    outer=json.loads(blob.decode());payload=outer["payload"]
    if payload.get("schema")!=SCHEMA:raise ValueError("unsupported networking snapshot schema")
    if sha256_hex(canonical_json_bytes(payload))!=outer.get("sha256"):raise ValueError("networking snapshot checksum mismatch")
    return payload["source_id"],tuple(SourceRecord(x["record_key"],base64.b64decode(x["raw_b64"]),x.get("upstream_version"),x.get("claimed_digest")) for x in payload["records"])
def replay_normalized(records,normalizer):
    return tuple(normalizer.normalize(r) for r in records)
