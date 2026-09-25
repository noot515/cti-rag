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
    optional_components:Tuple[str,...]=()
    def __post_init__(self):
        if self.name not in ("fixture","text-mvp","analytical","full-research"):raise ValueError("unknown deployment profile")
        if self.data_root_env!="CTI_RAG_DATA_ROOT":raise ValueError("deployment data root must be configurable through CTI_RAG_DATA_ROOT")
        if any(not p.startswith("api:") for p in self.exposed_ports):raise ValueError("only API ports may be externally exposed by profile contract")
        if self.egress_policy not in ("deny_all","deny_by_default","allowlist"):raise ValueError("unsupported egress policy")
        if self.egress_policy!="allowlist" and self.egress_allowlist:raise ValueError("egress allowlist requires allowlist policy")
        if any("=" in name or not name.strip() for name in self.secret_names):raise ValueError("profiles contain secret names, never literal secret values")

def load_profile(path):
    row=json.loads(Path(path).read_text(encoding="utf-8"))
    return DeploymentProfile(
        row["name"],tuple(row["components"]),tuple(row.get("exposed_ports",())),tuple(row.get("secret_names",())),
        bool(row["internal_network"]),row["egress_policy"],tuple(row.get("egress_allowlist",())),row["data_root_env"],
        tuple((str(v["service"]),str(v["cpu"]),str(v["memory"])) for v in row.get("resource_limits",())),
        tuple(row.get("optional_components",()))
    )
