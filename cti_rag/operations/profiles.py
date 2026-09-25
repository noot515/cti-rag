"""Deployment profile contracts for fixture through full-research operation."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Tuple

@dataclass(frozen=True)
class DeploymentProfile:
    name:str
    components:Tuple[str,...]
    exposed_ports:Tuple[str,...]
    secret_names:Tuple[str,...]
    internal_network:bool
    egress_policy:str
    egress_allowlist:Tuple[str,...]
    data_root_env:str
    resource_limits:Tuple[Tuple[str,str,str],...]
    service_egress:Tuple[Tuple[str,str],...]
    read_only_mounts:Tuple[Tuple[str,str,str],...]=()
    capability_drop:Tuple[Tuple[str,Tuple[str,...]],...]=()
    optional_components:Tuple[str,...]=()
    def __post_init__(self):
        if self.name not in ("fixture","text-mvp","analytical","full-research"):raise ValueError("unknown deployment profile")
        if self.data_root_env!="CTI_RAG_DATA_ROOT":raise ValueError("deployment data root must be configurable through CTI_RAG_DATA_ROOT")
        if any(not p.startswith("api:") for p in self.exposed_ports):raise ValueError("only API ports may be externally exposed by profile contract")
        if self.egress_policy not in ("deny_all","deny_by_default","allowlist"):raise ValueError("unsupported egress policy")
        if self.egress_policy!="allowlist" and self.egress_allowlist:raise ValueError("egress allowlist requires allowlist policy")
        if any("=" in name or not name.strip() for name in self.secret_names):raise ValueError("profiles contain secret names, never literal secret values")
        allowed_egress={"deny_all","internal_only","allowlist"}
        if any(policy not in allowed_egress for _service,policy in self.service_egress):raise ValueError("invalid per-service egress policy")
        known=set(self.components)|set(self.optional_components)
        if any(service not in known for service,_policy in self.service_egress):raise ValueError("per-service egress references unknown component")
        if any(service not in known or not source_env.strip() or not target.startswith("/") for service,source_env,target in self.read_only_mounts):raise ValueError("invalid restricted mount")
        if any(service not in known or not caps for service,caps in self.capability_drop):raise ValueError("invalid capability drop contract")

def load_profile(path):
    row=json.loads(Path(path).read_text(encoding="utf-8"))
    return DeploymentProfile(
        row["name"],tuple(row["components"]),tuple(row.get("exposed_ports",())),tuple(row.get("secret_names",())),
        bool(row["internal_network"]),row["egress_policy"],tuple(row.get("egress_allowlist",())),row["data_root_env"],
        tuple((str(v["service"]),str(v["cpu"]),str(v["memory"])) for v in row.get("resource_limits",())),
        tuple((str(service),str(policy)) for service,policy in sorted(row.get("service_egress",{}).items())),
        tuple((str(v["service"]),str(v["source_env"]),str(v["target"])) for v in row.get("read_only_mounts",()) if bool(v.get("read_only",False))),
        tuple((str(service),tuple(str(x) for x in caps)) for service,caps in sorted(row.get("capability_drop",{}).items())),
        tuple(row.get("optional_components",()))
    )
