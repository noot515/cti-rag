from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
from .errors import ValidationError

class AccessLabel(str, Enum):
    PUBLIC="public"; INTERNAL="internal"; CONFIDENTIAL="confidential"; RESTRICTED="restricted"; PRIVATE="private"
class ProcessingClass(str, Enum):
    LOCAL_ONLY="local_only"; LOCAL_OR_APPROVED_REMOTE="local_or_approved_remote"; APPROVED_REMOTE="approved_remote"
@dataclass(frozen=True)
class PolicyLabels:
    tenant_id: str
    access_label: AccessLabel
    processing_class: ProcessingClass
    license_id: Optional[str]=None
    retention_class: Optional[str]=None
    markings: Tuple[str,...]=()
    def __post_init__(self):
        if not self.tenant_id.strip(): raise ValidationError("policy tenant_id must be non-empty")
        if len(set(self.markings)) != len(self.markings): raise ValidationError("policy markings must be unique")
