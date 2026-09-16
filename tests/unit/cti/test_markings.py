from __future__ import annotations

from packages.domains.cti.markings import (
    CtiMarking,
    GranularMarking,
    TlpLabel,
    to_policy_metadata,
    unsupported_granular_selectors,
)


def test_tlp_amber_strict_is_preserved_without_numeric_ordering():
    marking = CtiMarking(marking_ref="m1", definition_type="tlp", definition={"tlp": "AMBER+STRICT"})
    assert marking.tlp_label() is TlpLabel.AMBER_STRICT
    policy = to_policy_metadata(source_instances=("s",), markings=(marking,), declared_marking_refs=("m1",))
    assert policy.dissemination == ("tlp:amber+strict",)


def test_missing_or_unsupported_marking_definition_is_unresolved():
    missing = to_policy_metadata(source_instances=("s",), declared_marking_refs=("missing",))
    assert missing.unresolved_markings is True
    statement = CtiMarking(marking_ref="m2", definition_type="statement", definition="internal")
    assert to_policy_metadata(
        source_instances=("s",), markings=(statement,), declared_marking_refs=("m2",)
    ).unresolved_markings is True


def test_unsupported_granular_selector_is_detected():
    good = GranularMarking(marking_ref="m", selectors=("description", "external_ids[0].value"))
    bad = GranularMarking(marking_ref="m", selectors=("x_private.secret",))
    assert unsupported_granular_selectors((good,)) == ()
    assert unsupported_granular_selectors((bad,)) == ("x_private.secret",)
