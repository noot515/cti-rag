from __future__ import annotations

from pathlib import Path

import pytest

from packages.evidence.config import (
    AdvancedRagConfigError,
    RuntimeFactories,
    load_advanced_rag_config,
)


def test_defaults_are_disabled_and_fixture_is_offline():
    cfg = load_advanced_rag_config(environ={})
    assert cfg.enabled is False
    assert cfg.profile == "fixture"
    assert cfg.network.allow_outbound is False
    assert cfg.network.allow_downloads is False
    assert cfg.network.web_search is False
    assert cfg.graph.max_hops <= 3
    assert 1 <= cfg.channels.dense_top_k <= 50


def test_tavily_environment_does_not_enable_fixture_networking():
    cfg = load_advanced_rag_config(environ={"TAVILY_API_KEY": "sentinel"})
    assert cfg.network.web_search is False
    assert cfg.network.allow_outbound is False


def test_documented_boolean_environment_override_is_strict():
    cfg = load_advanced_rag_config(environ={"ADVANCED_RAG_ENABLED": "false"})
    assert cfg.enabled is False

    cfg = load_advanced_rag_config(environ={"ADVANCED_RAG_ENABLED": "true"})
    assert cfg.enabled is True

    with pytest.raises(AdvancedRagConfigError, match="ADVANCED_RAG_ENABLED"):
        load_advanced_rag_config(environ={"ADVANCED_RAG_ENABLED": "definitely"})


def test_unknown_nested_configuration_key_is_rejected(tmp_path: Path):
    path = tmp_path / "advanced.yaml"
    path.write_text("channels:\n  dense_top_k: 10\n  surprise: true\n", encoding="utf-8")
    with pytest.raises(AdvancedRagConfigError, match="surprise"):
        load_advanced_rag_config(path, environ={})


@pytest.mark.parametrize(
    "overrides, expected_fragment",
    [
        ({"channels": {"dense_top_k": 51}}, "less than or equal to 50"),
        ({"channels": {"lexical_top_k": 0}}, "greater than or equal to 1"),
        ({"graph": {"max_hops": 4}}, "less than or equal to 3"),
        ({"context": {"max_tokens": 128, "reserve_tokens": 129}}, "reserve_tokens"),
    ],
)
def test_bounds_are_validated(overrides, expected_fragment):
    with pytest.raises(AdvancedRagConfigError, match=expected_fragment):
        load_advanced_rag_config(environ={}, trusted_overrides=overrides)


def test_fixture_profile_cannot_be_reenabled_for_networking():
    with pytest.raises(AdvancedRagConfigError, match="fixture profile forbids"):
        load_advanced_rag_config(
            environ={"TAVILY_API_KEY": "sentinel"},
            trusted_overrides={"network": {"web_search": True, "allow_outbound": True}},
        )


def test_fixture_profile_rejects_remote_provider():
    with pytest.raises(AdvancedRagConfigError, match="local embedding provider"):
        load_advanced_rag_config(
            environ={},
            trusted_overrides={
                "providers": {
                    "embedding": {
                        "provider": "remote-example",
                        "model": "embed-v1",
                        "revision": "2026-09-16",
                        "dimension": 768,
                        "normalization": "l2",
                        "remote": True,
                    }
                }
            },
        )


def test_services_profile_can_explicitly_enable_outbound_networking():
    cfg = load_advanced_rag_config(
        environ={},
        trusted_overrides={
            "profile": "services",
            "network": {"allow_outbound": True, "allow_downloads": False, "web_search": False},
        },
    )
    assert cfg.profile == "services"
    assert cfg.network.allow_outbound is True


def test_runtime_factories_are_inert_and_fixture_rejects_web_or_opencti_factories():
    calls = []

    def factory():
        calls.append("called")
        return object()

    factories = RuntimeFactories(embedding_factory=factory)
    cfg = load_advanced_rag_config(environ={})
    factories.validate_for(cfg)
    assert calls == []

    with pytest.raises(AdvancedRagConfigError, match="fixture profile"):
        RuntimeFactories(web_factory=factory).validate_for(cfg)
    assert calls == []


def test_json_and_yaml_files_round_trip_without_secrets(tmp_path: Path):
    yaml_path = tmp_path / "advanced.yaml"
    yaml_path.write_text(
        "profile: services\nenabled: true\nchannels:\n  dense_top_k: 12\n",
        encoding="utf-8",
    )
    cfg = load_advanced_rag_config(yaml_path, environ={})
    assert cfg.enabled is True
    assert cfg.channels.dense_top_k == 12
    snapshot = cfg.serializable_snapshot()
    rendered = str(snapshot).lower()
    for forbidden in ("api_key", "access_token", "password", "secret_key", "bearer"):
        assert forbidden not in rendered
