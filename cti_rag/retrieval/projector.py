"""Structure-aware JSON passage projection preserving original text and source locators."""
from __future__ import annotations
import json,re,unicodedata
from datetime import datetime
from cti_rag.contracts import ComponentFingerprint,EpistemicKind,EpistemicMetadata,JsonPointerLocator,Passage,locator_to_data
from cti_rag.retrieval.models import ExactRecord,LexicalDocument

def _pointer_get(data,pointer):
    if pointer=="": return data
    current=data
    for part in pointer.lstrip("/").split("/"):
        key=part.replace("~1","/").replace("~0","~")
        current=current[int(key)] if isinstance(current,list) else current[key]
    return current

def normalize_search_text(text):
    return re.sub(r"\s+"," ",unicodedata.normalize("NFKC",text)).strip()

class StructuredJsonProjector:
    def __init__(self,analyzer_version="unicode61/1",chunker=None):
        self.analyzer_version=analyzer_version; self.chunker=chunker or ComponentFingerprint("json-pointer-field","1")
    def project(self,*,normalized_bytes,artifact_uid,revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,access_label,available_at=None,valid_from=None,valid_to=None,text_pointers=("/summary",),context_prefix=""):
        data=json.loads(normalized_bytes.decode("utf-8"))
        exact_locator=JsonPointerLocator("/id")
        exact=ExactRecord(revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,access_label,available_at,valid_from,valid_to,json.dumps(locator_to_data(exact_locator),sort_keys=True,separators=(",",":")),canonical_id)
        docs=[]
        for pointer in text_pointers:
            value=_pointer_get(data,pointer)
            if not isinstance(value,str) or not value.strip(): continue
            original=value
            locator=JsonPointerLocator(pointer)
            passage=Passage(artifact_uid,revision_uid,locator,original,self.chunker,EpistemicMetadata(EpistemicKind.SOURCE_CLAIM))
            docs.append(LexicalDocument(
                passage.passage_uid,revision_uid,object_uid,namespace,object_type,canonical_id,domain,source_id,tenant_id,access_label,
                available_at,valid_from,valid_to,json.dumps(locator_to_data(locator),sort_keys=True,separators=(",",":")),
                original,normalize_search_text(original),normalize_search_text(context_prefix),self.analyzer_version,
            ))
        return exact,tuple(docs)
