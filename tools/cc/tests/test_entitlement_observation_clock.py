"""A superseded observation evaluates the current record at completion time."""
from datetime import datetime, timedelta, timezone
import threading

import pytest

from cc.core.ecosystem import entitlement


@pytest.mark.parametrize(
    "latest_status,elapsed,fixed_now,expected_state,eligible",
    [
        (200, 3, False, "offline-cached", True),
        (404, 3, False, "unentitled", False),
        (200, 1, False, "offline-unverified", False),
        (200, 72 * 3600 + 3, False, "stale-entitlement", False),
        (200, 3, True, "offline-unverified", False),
    ],
)
def test_superseded_probe_uses_completion_clock_without_weakening_time_checks(
    tmp_path, monkeypatch, latest_status, elapsed, fixed_now, expected_state, eligible
):
    started = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
    clock = [started]
    real_utc = entitlement._utc
    monkeypatch.setattr(
        entitlement, "_utc",
        lambda value=None: real_utc(value) if value is not None else clock[0],
    )
    reconciled = []
    monkeypatch.setattr(
        entitlement, "_reconcile_knowledge_snapshot_authority",
        lambda _layer, decision, **_kwargs: reconciled.append(decision),
    )
    layer = {
        "id": "clock-test", "role": "department", "product": "knowledge",
        "auth": "work", "source": {"repo": "git@github.com:example/knowledge.git"},
    }
    ledger = tmp_path / "ledger.json"
    entered, release = threading.Event(), threading.Event()
    results, errors = [], []

    def delayed_denial(*_args):
        entered.set()
        assert release.wait(5)
        return 404

    def old_probe():
        try:
            results.append(entitlement.observe_layer(
                layer, login="person", token="synthetic", get_json=delayed_denial,
                state_path=ledger, now=started if fixed_now else None,
            ))
        except BaseException as error:
            errors.append(error)

    old = threading.Thread(target=old_probe)
    old.start()
    try:
        assert entered.wait(5)
        clock[0] = started + timedelta(seconds=2)
        current = entitlement.observe_layer(
            layer, login="new-person", token="synthetic",
            get_json=lambda *_args: latest_status, state_path=ledger,
        )
        assert current.eligible is (latest_status == 200)
        committed = ledger.read_bytes()
        clock[0] = started + timedelta(seconds=elapsed)
    finally:
        release.set()
        old.join(5)
    assert not old.is_alive()
    assert errors == []
    assert len(results) == 1
    assert results[0].superseded is True
    assert results[0].state == expected_state
    assert results[0].eligible is eligible
    assert reconciled[-1] == results[0]
    assert ledger.read_bytes() == committed
