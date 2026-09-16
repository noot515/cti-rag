from __future__ import annotations

import inspect

from packages.evidence.ids import object_uid
from packages.evidence.schema import ObjectCandidate
from packages.retrieval.candidate import BackendHit, Channel, ChannelResult


def test_backend_hit_is_not_an_authorized_candidate():
    uid = object_uid("cti", "s", "o")
    hit = BackendHit(backend_key="row-1", domain="cti", scope_id="scope-a", snapshot_id="snap-1",
                     logical_uid=uid, raw_score=0.7)
    assert not isinstance(hit, ObjectCandidate)
    assert not hasattr(hit, "authorized_view")


def test_channel_contract_has_required_search_signature():
    sig = inspect.signature(Channel.search)
    assert list(sig.parameters) == ["self", "plan", "scope", "snapshot", "deadline"]


def test_channel_result_requires_reason_for_timeout():
    try:
        ChannelResult(channel="dense", status="timeout")
    except Exception as exc:
        assert "reason" in str(exc)
    else:
        raise AssertionError("timeout without reason must fail validation")
