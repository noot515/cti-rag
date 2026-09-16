from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap


ROOT = Path(__file__).resolve().parents[3]


def _run_isolated(code: str, tmp_path: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "PYTHONIOENCODING": "utf-8",
        "TAVILY_API_KEY": "sentinel-must-not-enable-network",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_pure_imports_do_not_create_runtime_state_or_connect(tmp_path: Path):
    code = textwrap.dedent(
        f"""
        import json
        import socket
        import sys
        import threading
        from pathlib import Path

        sys.path.insert(0, {str(ROOT)!r})
        cwd = Path.cwd()
        before = {{p.name for p in cwd.iterdir()}}
        before_threads = [t.name for t in threading.enumerate()]

        def blocked_connect(*args, **kwargs):
            raise AssertionError("network connect attempted during pure import")

        socket.socket.connect = blocked_connect
        socket.create_connection = blocked_connect

        import packages
        import packages.core
        from packages.evidence.config import AdvancedRagConfig, load_advanced_rag_config
        from packages.evidence.schema import EvidenceObject
        from packages.evidence.policy import DenyByDefaultPolicy
        from packages.domains.cti import CtiDomainAdapter

        cfg = load_advanced_rag_config(environ={{"TAVILY_API_KEY": "sentinel"}})
        assert isinstance(cfg, AdvancedRagConfig)
        assert cfg.profile == "fixture"
        assert cfg.network.allow_outbound is False
        assert cfg.network.web_search is False
        assert "packages.core.knowledgebase" not in sys.modules
        assert "packages.core.graphbase" not in sys.modules
        assert EvidenceObject is not None
        assert DenyByDefaultPolicy is not None
        assert CtiDomainAdapter is not None
        assert "packages.models" not in sys.modules
        assert "packages.utils.logging_config" not in sys.modules
        assert [t.name for t in threading.enumerate()] == before_threads
        assert {{p.name for p in cwd.iterdir()}} == before
        print(json.dumps({{"ok": True, "files": sorted(before)}}))
        """
    )
    result = _run_isolated(code, tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["ok"] is True


def test_packages_config_submodule_collision_remains_lazy(tmp_path: Path):
    code = textwrap.dedent(
        f"""
        import socket
        import sys
        import types
        from pathlib import Path

        sys.path.insert(0, {str(ROOT)!r})
        socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))

        import packages
        facade = packages.config
        assert "packages.config" not in sys.modules
        assert "lazy legacy Config proxy" in repr(facade)

        import packages.config as config_module
        assert isinstance(packages.config, types.ModuleType)
        assert config_module.Config is not None
        assert config_module.get_runtime_config is not None
        assert config_module._runtime_config is None
        assert not Path("saves").exists()
        """
    )
    result = _run_isolated(code, tmp_path)
    assert result.returncode == 0, result.stderr


def test_executor_is_constructed_only_on_explicit_access(tmp_path: Path):
    code = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        import packages
        assert packages._executor is None
        executor = packages.get_executor()
        assert packages._executor is executor
        executor.shutdown(wait=True)
        """
    )
    result = _run_isolated(code, tmp_path)
    assert result.returncode == 0, result.stderr
