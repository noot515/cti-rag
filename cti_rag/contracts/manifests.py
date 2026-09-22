from dataclasses import dataclass
from datetime import datetime
from typing import Tuple
from .errors import ValidationError
from .temporal import ensure_utc
@dataclass(frozen=True)
class SnapshotManifestRef:
    manifest_id:str; corpus_digest:str; created_at:datetime; index_generation_ids:Tuple[str,...]=(); schema_version:str="snapshot-manifest-ref/1"
    def __post_init__(self):
        if not self.manifest_id.strip() or not self.corpus_digest.strip(): raise ValidationError("snapshot fields required")
        ensure_utc(self.created_at)
