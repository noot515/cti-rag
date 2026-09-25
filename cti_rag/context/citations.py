"""Citation verification after packing/truncation."""
from __future__ import annotations

class CitationVerifier:
    def __init__(self,evidence_store):self.evidence_store=evidence_store
    def verify(self,packed):
        if self.evidence_store is None:return False
        payload=self.evidence_store.resolve(packed.evidence.passage.provenance)
        if payload is None:return False
        if isinstance(payload,bytes):
            try:source=payload.decode("utf-8")
            except UnicodeDecodeError:return False
        else:source=str(payload)
        if packed.truncated:return source.startswith(packed.display_text)
        return source==packed.display_text
