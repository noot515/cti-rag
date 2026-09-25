"""Mounted-file secret resolution for hardened Phase 22 deployment profiles."""
from __future__ import annotations
import os
from pathlib import Path

class SecretConfigurationError(RuntimeError):pass

def resolve_profile_secrets(profile,environ=None):
    env=os.environ if environ is None else environ
    resolved={}
    for name in profile.secret_names:
        if env.get(name):
            raise SecretConfigurationError(f"literal environment secret disabled for hardened profile: {name}")
        file_var=f"{name}_FILE";path=env.get(file_var)
        if not path:raise SecretConfigurationError(f"missing mounted secret path: {file_var}")
        target=Path(path)
        if not target.is_file():raise SecretConfigurationError(f"secret file unavailable: {file_var}")
        value=target.read_text(encoding="utf-8").rstrip("\r\n")
        if not value:raise SecretConfigurationError(f"secret file is empty: {file_var}")
        resolved[name]=value
    return resolved

def apply_profile_secrets(profile,environ=None):
    env=os.environ if environ is None else environ
    values=resolve_profile_secrets(profile,env)
    for name,value in values.items():env[name]=value
    return tuple(sorted(values))
