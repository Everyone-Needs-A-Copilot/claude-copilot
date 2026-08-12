from __future__ import annotations

import json
import multiprocessing as mp
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cc.commands.layers import GITHUB_KEYCHAIN_SERVICE, build_layers_join_report
from cc.commands.update import build_update_report
from cc.core.ecosystem import entitlement
from cc.core.ecosystem.policy import permissive_policy
from cc.core.ecosystem.project_sources import resolve_claude_content

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _delayed_observation_process(
    layer: dict,
    state_path: str,
    status: int | None,
    now: datetime,
    started,
    release,
    results,
) -> None:
    def delayed(_url: str, _token: str) -> int | None:
        started.set()
        if not release.wait(10):
            raise RuntimeError("race fixture release timed out")
        return status

    decision = entitlement.observe_layer(
        layer,
        login="octocat",
        token="fixture",
        get_json=delayed,
        state_path=state_path,
        now=now,
    )
    results.put((decision.state, decision.eligible))


def _crash_during_probe_process(layer: dict, state_path: str, started) -> None:
    def crash(_url: str, _token: str) -> int | None:
        started.set()
        os._exit(19)

    entitlement.observe_layer(
        layer,
        login="octocat",
        token="fixture",
        get_json=crash,
        state_path=state_path,
        now=NOW + timedelta(minutes=1),
    )


def _crash_holding_ledger_lock_process(state_path: str, started) -> None:
    path = Path(state_path)
    with entitlement.advisory_file_lock(
        entitlement._ledger_lock_path(path), blocking=True
    ):
        started.set()
        os._exit(23)


def _delayed_update_process(
    layer: dict,
    state_path: str,
    lock_path: str,
    output: str,
    mirror_root: str,
    status: int | None,
    now: datetime,
    started,
    release,
    results,
) -> None:
    def delayed(_url: str, _token: str) -> int | None:
        started.set()
        if not release.wait(10):
            raise RuntimeError("update race release timed out")
        return status

    previous = json.loads(Path(lock_path).read_text(encoding="utf-8"))
    report = build_update_report(
        _layers=[layer],
        _previous_lock=previous,
        _mirror_root=mirror_root,
        _materialize_root=output,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
        _personal_roots=[],
        _entitlement_login="octocat",
        _entitlement_token="fixture",
        _entitlement_get_json=delayed,
        _entitlement_state_path=state_path,
        _entitlement_now=now,
    )
    results.put(report)


def _crash_revision_lease_process(
    state_path: str, decision: entitlement.EntitlementDecision, started
) -> None:
    def crash() -> None:
        started.set()
        os._exit(29)

    entitlement.run_under_revision_lease(
        state_path=state_path,
        decisions=[decision],
        action=crash,
    )


def _binding_lease_process(bindings, started, release, results, crash: bool) -> None:
    def action() -> str:
        started.set()
        if crash:
            os._exit(31)
        if not release.wait(10):
            raise RuntimeError("binding lease fixture release timed out")
        return "committed"

    valid, value = entitlement.run_under_binding_leases(bindings, action)
    results.put((valid, value))


def _layer(
    layer_id: str,
    *,
    product: str,
    role: str,
    rank: int,
    path: Path,
    auth: str = "work",
) -> dict:
    return {
        "id": layer_id,
        "role": role,
        "rank": rank,
        "product": product,
        "source": {
            "repo": f"fixture-org/{layer_id}",
            "ref": "main",
            "path": str(path),
        },
        "auth": auth,
        "activation": "always",
    }


def _observe(
    layer: dict,
    state_path: Path,
    status: int | None,
    *,
    now: datetime = NOW,
) -> entitlement.EntitlementDecision:
    return entitlement.observe_layer(
        layer,
        login="octocat",
        token="not-persisted",
        get_json=lambda _url, _token: status,
        state_path=state_path,
        now=now,
    )


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_github_repo_identity_normalizes_supported_transport_spellings() -> None:
    assert entitlement.github_repo_slug("owner/repo.git") == "owner/repo"
    assert entitlement.github_repo_slug("https://github.com/owner/repo.git") == (
        "owner/repo"
    )
    assert entitlement.github_repo_slug("git@github.com:owner/repo.git") == "owner/repo"
    assert entitlement.github_repo_slug("git@github-work:owner/repo.git") == (
        "owner/repo"
    )
    assert entitlement.github_repo_slug("file:///protected/repo") is None


def test_entitlement_lifecycle_is_bounded_identity_bound_and_token_free(
    tmp_path: Path,
) -> None:
    state = tmp_path / "private" / "entitlements.json"
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )

    unentitled = _observe(layer, state, 404)
    assert (unentitled.state, unentitled.eligible) == ("unentitled", False)
    assert unentitled.responsible_actor == "organization-access-owner"

    entitled = _observe(layer, state, 200, now=NOW + timedelta(minutes=1))
    assert (entitled.state, entitled.eligible) == ("entitled", True)

    cached = _observe(layer, state, None, now=NOW + timedelta(hours=71))
    assert (cached.state, cached.eligible) == ("offline-cached", True)

    stale = _observe(layer, state, None, now=NOW + timedelta(hours=73))
    assert (stale.state, stale.eligible) == ("stale-entitlement", False)
    assert stale.responsible_actor == "person"

    revoked = _observe(layer, state, 404, now=NOW + timedelta(hours=74))
    assert (revoked.state, revoked.eligible) == ("revoked", False)
    assert revoked.responsible_actor == "organization-access-owner"

    still_revoked = _observe(layer, state, None, now=NOW + timedelta(hours=75))
    assert (still_revoked.state, still_revoked.eligible) == ("revoked", False)

    signed_out_after_revocation = entitlement.observe_layer(
        layer,
        login=None,
        token=None,
        state_path=state,
        now=NOW + timedelta(hours=75, minutes=30),
    )
    assert (
        signed_out_after_revocation.state,
        signed_out_after_revocation.eligible,
    ) == (
        "revoked",
        False,
    )

    reauthorized = _observe(layer, state, 200, now=NOW + timedelta(hours=76))
    assert (reauthorized.state, reauthorized.eligible) == ("entitled", True)

    raw = state.read_text(encoding="utf-8")
    assert "not-persisted" not in raw
    assert state.stat().st_mode & 0o777 == 0o600
    assert state.parent.stat().st_mode & 0o777 == 0o700


def test_signed_out_observation_blocks_offline_cache_until_live_reauthorization(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    assert _observe(layer, state, 200).eligible

    signed_out = entitlement.observe_layer(
        layer,
        login="octocat",
        token=None,
        state_path=state,
        now=NOW + timedelta(minutes=1),
    )
    assert (signed_out.state, signed_out.eligible) == ("signed-out", False)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=2),
    )
    assert eligible == []
    assert decisions[0].state == "signed-out"

    offline = _observe(layer, state, None, now=NOW + timedelta(minutes=3))
    assert (offline.state, offline.eligible) == ("signed-out", False)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=4),
    )
    assert eligible == []
    assert decisions[0].state == "signed-out"

    reauthorized = _observe(layer, state, 200, now=NOW + timedelta(minutes=5))
    assert (reauthorized.state, reauthorized.eligible) == ("entitled", True)


@pytest.mark.parametrize("blocked_status", [403, 404])
def test_never_entitled_observation_stays_blocked_offline_until_live_200(
    tmp_path: Path, blocked_status: int
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "knowledge-department",
        product="knowledge",
        role="department",
        rank=20,
        path=tmp_path / "source",
    )
    first = _observe(layer, state, blocked_status)
    assert (first.state, first.eligible) == ("unentitled", False)
    offline = _observe(layer, state, None, now=NOW + timedelta(minutes=1))
    assert (offline.state, offline.eligible) == ("unentitled", False)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer], state_path=state, login="octocat", now=NOW + timedelta(minutes=2)
    )
    assert eligible == []
    assert decisions[0].state == "unentitled"
    assert _observe(layer, state, 200, now=NOW + timedelta(minutes=3)).eligible


@pytest.mark.parametrize("product", ["claude", "codex", "cli", "knowledge"])
@pytest.mark.parametrize("blocking_state", ["signed-out", "unentitled", "revoked"])
def test_blocking_state_transition_property_never_revives_from_offline_cache(
    tmp_path: Path, product: str, blocking_state: str
) -> None:
    state = tmp_path / product / blocking_state / "entitlements.json"
    layer = _layer(
        f"{product}-organization",
        product=product,
        role="organization",
        rank=30,
        path=tmp_path / product / "source",
    )
    if blocking_state in {"signed-out", "revoked"}:
        assert _observe(layer, state, 200, now=NOW).eligible
    if blocking_state == "signed-out":
        blocked = entitlement.observe_layer(
            layer,
            login="octocat",
            token=None,
            state_path=state,
            now=NOW + timedelta(minutes=1),
        )
    else:
        blocked = _observe(layer, state, 404, now=NOW + timedelta(minutes=1))
    assert (blocked.state, blocked.eligible) == (blocking_state, False)

    # Check both an observation and the read-only consumer path. Neither may
    # reinterpret the retained last_entitled_at as offline-cache authority.
    offline = _observe(layer, state, None, now=NOW + timedelta(minutes=2))
    assert (offline.state, offline.eligible) == (blocking_state, False)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=3),
    )
    assert eligible == []
    assert decisions[0].state == blocking_state

    restored = _observe(layer, state, 200, now=NOW + timedelta(minutes=4))
    assert (restored.state, restored.eligible) == ("entitled", True)


@pytest.mark.parametrize(
    ("field", "offset"),
    [
        ("checked_at", timedelta(microseconds=1)),
        ("checked_at", timedelta(seconds=1)),
        ("checked_at", timedelta(hours=72)),
        ("last_entitled_at", timedelta(microseconds=1)),
        ("last_entitled_at", timedelta(seconds=1)),
        ("last_entitled_at", timedelta(hours=72)),
    ],
)
def test_future_ledger_timestamps_never_extend_offline_grace(
    tmp_path: Path, field: str, offset: timedelta
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "codex-organization",
        product="codex",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    assert _observe(layer, state, 200, now=NOW - timedelta(minutes=1)).eligible
    payload = json.loads(state.read_text(encoding="utf-8"))
    payload["layers"][layer["id"]][field] = (
        (NOW + offset).isoformat().replace("+00:00", "Z")
    )
    state.write_text(json.dumps(payload), encoding="utf-8")
    state.chmod(0o600)

    eligible, decisions = entitlement.filter_eligible_layers(
        [layer], state_path=state, login="octocat", now=NOW
    )
    assert eligible == []
    assert decisions[0].state == "offline-unverified"
    assert decisions[0].expires_at is None

    # An offline observation quarantines rather than carrying the impossible
    # grant forward. Only a fresh live 200 can restore eligibility.
    offline = _observe(layer, state, None, now=NOW)
    assert (offline.state, offline.eligible) == ("offline-unverified", False)
    assert _observe(layer, state, 200, now=NOW + timedelta(seconds=1)).eligible


def test_delayed_offline_process_cannot_replay_over_newer_live_revocation(
    tmp_path: Path,
) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    assert _observe(layer, state, 200, now=NOW).eligible
    started, release, results = context.Event(), context.Event(), context.Queue()
    delayed = context.Process(
        target=_delayed_observation_process,
        args=(
            layer,
            str(state),
            None,
            NOW + timedelta(minutes=1),
            started,
            release,
            results,
        ),
    )
    delayed.start()
    assert started.wait(10)

    revoked = _observe(layer, state, 404, now=NOW + timedelta(minutes=2))
    assert (revoked.state, revoked.eligible) == ("revoked", False)
    release.set()
    delayed.join(10)
    assert delayed.exitcode == 0
    assert results.get(timeout=2)[1] is False

    eligible, decisions = entitlement.filter_eligible_layers(
        [layer],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=3),
    )
    assert eligible == []
    assert decisions[0].state == "revoked"


def test_later_live_200_reauthorization_wins_when_older_live_denial_finishes_last(
    tmp_path: Path,
) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "codex-organization",
        product="codex",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    assert _observe(layer, state, 200, now=NOW).eligible
    started, release, results = context.Event(), context.Event(), context.Queue()
    older_denial = context.Process(
        target=_delayed_observation_process,
        args=(
            layer,
            str(state),
            404,
            NOW + timedelta(minutes=1),
            started,
            release,
            results,
        ),
    )
    older_denial.start()
    assert started.wait(10)

    reauthorized = _observe(layer, state, 200, now=NOW + timedelta(minutes=2))
    assert (reauthorized.state, reauthorized.eligible) == ("entitled", True)
    release.set()
    older_denial.join(10)
    assert older_denial.exitcode == 0
    # The older denial returns the current decision and cannot overwrite it.
    assert results.get(timeout=2)[1] is False
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=3),
    )
    assert eligible == [layer]
    assert decisions[0].state == "offline-cached"


def test_concurrent_different_layers_preserve_both_observations(tmp_path: Path) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    claude = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "claude",
    )
    knowledge = _layer(
        "knowledge-department",
        product="knowledge",
        role="department",
        rank=20,
        path=tmp_path / "knowledge",
    )
    assert _observe(claude, state, 200, now=NOW).eligible
    assert _observe(knowledge, state, 200, now=NOW).eligible
    started, release, results = context.Event(), context.Event(), context.Queue()
    delayed = context.Process(
        target=_delayed_observation_process,
        args=(
            claude,
            str(state),
            None,
            NOW + timedelta(minutes=1),
            started,
            release,
            results,
        ),
    )
    delayed.start()
    assert started.wait(10)
    assert (
        _observe(knowledge, state, 404, now=NOW + timedelta(minutes=2)).state
        == "revoked"
    )
    release.set()
    delayed.join(10)
    assert delayed.exitcode == 0
    assert results.get(timeout=2) == ("offline-cached", True)

    eligible, decisions = entitlement.filter_eligible_layers(
        [claude, knowledge],
        state_path=state,
        login="octocat",
        now=NOW + timedelta(minutes=3),
    )
    assert eligible == [claude]
    assert {item.layer: item.state for item in decisions} == {
        "claude-organization": "offline-cached",
        "knowledge-department": "revoked",
    }


def test_crashed_probe_and_stale_os_lock_are_recoverable(tmp_path: Path) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    layer = _layer(
        "cli-organization",
        product="cli",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    assert _observe(layer, state, 200, now=NOW).eligible

    probe_started = context.Event()
    crashed_probe = context.Process(
        target=_crash_during_probe_process,
        args=(layer, str(state), probe_started),
    )
    crashed_probe.start()
    assert probe_started.wait(10)
    crashed_probe.join(10)
    assert crashed_probe.exitcode == 19

    lock_started = context.Event()
    crashed_lock = context.Process(
        target=_crash_holding_ledger_lock_process,
        args=(str(state), lock_started),
    )
    crashed_lock.start()
    assert lock_started.wait(10)
    crashed_lock.join(10)
    assert crashed_lock.exitcode == 23

    # flock ownership is released by the OS; the persistent mode-0600 lockfile
    # is not interpreted as a live/stale PID marker.
    revoked = _observe(layer, state, 404, now=NOW + timedelta(minutes=2))
    assert (revoked.state, revoked.eligible) == ("revoked", False)
    lock_path = entitlement._ledger_lock_path(state)
    assert lock_path.stat().st_mode & 0o777 == 0o600
    assert state.stat().st_mode & 0o777 == 0o600
    assert state.parent.stat().st_mode & 0o777 == 0o700


def test_symlinked_ledger_lock_fails_closed_before_observation(tmp_path: Path) -> None:
    state = tmp_path / "private" / "entitlements.json"
    state.parent.mkdir(mode=0o700)
    lock_path = entitlement._ledger_lock_path(state)
    target = tmp_path / "outside.lock"
    target.write_text("do not follow", encoding="utf-8")
    lock_path.symlink_to(target)
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "source",
    )
    with pytest.raises(OSError):
        _observe(layer, state, 200)
    assert not state.exists()
    assert target.read_text(encoding="utf-8") == "do not follow"


def test_superseded_older_denial_update_cannot_prune_later_reauthorization(
    tmp_path: Path,
) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    source = tmp_path / "source"
    _write(source, "commands/protocol.md", "protected\n")
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=source,
    )
    lock_path = tmp_path / "copilot.lock.json"
    output = tmp_path / "materialized"
    common = {
        "_layers": [layer],
        "_mirror_root": tmp_path / "mirrors",
        "_materialize_root": output,
        "_lock_write_path": lock_path,
        "_policy": permissive_policy,
        "_personal_roots": [],
        "_entitlement_login": "octocat",
        "_entitlement_token": "fixture",
        "_entitlement_state_path": state,
    }
    build_update_report(
        _previous_lock={},
        _entitlement_get_json=lambda *_: 200,
        _entitlement_now=NOW,
        **common,
    )
    before_bytes = (output / "commands/protocol.md").read_bytes()

    started, release, results = context.Event(), context.Event(), context.Queue()
    older = context.Process(
        target=_delayed_update_process,
        args=(
            layer,
            str(state),
            str(lock_path),
            str(output),
            str(tmp_path / "mirrors"),
            404,
            NOW + timedelta(minutes=1),
            started,
            release,
            results,
        ),
    )
    older.start()
    assert started.wait(10)
    previous = json.loads(lock_path.read_text(encoding="utf-8"))
    newer = build_update_report(
        _previous_lock=previous,
        _entitlement_get_json=lambda *_: 200,
        _entitlement_now=NOW + timedelta(minutes=2),
        **common,
    )
    assert newer["result"] in {"applied", "up-to-date"}
    lock_after_newer = lock_path.read_bytes()
    release.set()
    older.join(10)
    assert older.exitcode == 0
    superseded = results.get(timeout=2)
    assert superseded["result"] == "held"
    assert superseded["changed"] == []
    assert (output / "commands/protocol.md").read_bytes() == before_bytes
    assert lock_path.read_bytes() == lock_after_newer
    assert "claude-organization" in json.loads(lock_path.read_text())


def test_superseded_older_entitled_update_cannot_restore_after_later_revocation(
    tmp_path: Path,
) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    source = tmp_path / "source"
    _write(source, "commands/protocol.md", "protected\n")
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=source,
    )
    lock_path = tmp_path / "copilot.lock.json"
    output = tmp_path / "materialized"
    common = {
        "_layers": [layer],
        "_mirror_root": tmp_path / "mirrors",
        "_materialize_root": output,
        "_lock_write_path": lock_path,
        "_policy": permissive_policy,
        "_personal_roots": [],
        "_entitlement_login": "octocat",
        "_entitlement_token": "fixture",
        "_entitlement_state_path": state,
    }
    build_update_report(
        _previous_lock={},
        _entitlement_get_json=lambda *_: 200,
        _entitlement_now=NOW,
        **common,
    )
    started, release, results = context.Event(), context.Event(), context.Queue()
    older = context.Process(
        target=_delayed_update_process,
        args=(
            layer,
            str(state),
            str(lock_path),
            str(output),
            str(tmp_path / "mirrors"),
            200,
            NOW + timedelta(minutes=1),
            started,
            release,
            results,
        ),
    )
    older.start()
    assert started.wait(10)
    previous = json.loads(lock_path.read_text(encoding="utf-8"))
    newer = build_update_report(
        _previous_lock=previous,
        _entitlement_get_json=lambda *_: 404,
        _entitlement_now=NOW + timedelta(minutes=2),
        **common,
    )
    assert newer["result"] == "blocked"
    assert not (output / "commands/protocol.md").exists()
    lock_after_newer = lock_path.read_bytes()
    release.set()
    older.join(10)
    assert older.exitcode == 0
    superseded = results.get(timeout=2)
    assert superseded["result"] == "held"
    assert not (output / "commands/protocol.md").exists()
    assert lock_path.read_bytes() == lock_after_newer
    assert "claude-organization" not in json.loads(lock_path.read_text())


def test_revision_lease_is_per_layer_and_crash_recoverable(tmp_path: Path) -> None:
    context = mp.get_context("fork")
    state = tmp_path / "state" / "entitlements.json"
    claude = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=tmp_path / "claude",
    )
    codex = _layer(
        "codex-department",
        product="codex",
        role="department",
        rank=20,
        path=tmp_path / "codex",
    )
    claude_decision = _observe(claude, state, 200, now=NOW)
    assert claude_decision.revision is not None
    # A newer observation for another layer does not invalidate Claude's
    # per-layer generation.
    assert _observe(codex, state, 404, now=NOW + timedelta(minutes=1)).state == (
        "unentitled"
    )
    ran: list[str] = []
    valid, value = entitlement.run_under_revision_lease(
        state_path=state,
        decisions=[claude_decision],
        action=lambda: ran.append("committed") or "ok",
    )
    assert (valid, value, ran) == (True, "ok", ["committed"])

    started = context.Event()
    crashed = context.Process(
        target=_crash_revision_lease_process,
        args=(str(state), claude_decision, started),
    )
    crashed.start()
    assert started.wait(10)
    crashed.join(10)
    assert crashed.exitcode == 29
    # OS-released lease permits the next observation and its later generation
    # invalidates the old plan without invoking the action.
    newer = _observe(claude, state, 404, now=NOW + timedelta(minutes=2))
    assert newer.state == "revoked"
    ran.clear()
    valid, value = entitlement.run_under_revision_lease(
        state_path=state,
        decisions=[claude_decision],
        action=lambda: ran.append("unsafe"),
    )
    assert (valid, value, ran) == (False, None, [])


def test_private_binding_leases_order_multiple_ledgers_and_release_after_crash(
    tmp_path: Path,
) -> None:
    context = mp.get_context("fork")
    first_state = tmp_path / "first" / "entitlements.json"
    second_state = tmp_path / "second" / "entitlements.json"
    first_layer = _layer(
        "codex-organization",
        product="codex",
        role="organization",
        rank=20,
        path=tmp_path / "first-source",
    )
    second_layer = _layer(
        "codex-department",
        product="codex",
        role="department",
        rank=30,
        path=tmp_path / "second-source",
    )
    first_decision = _observe(first_layer, first_state, 200)
    second_decision = _observe(second_layer, second_state, 200)
    first = entitlement.bind_layer_decisions(
        [first_layer],
        [first_decision],
        state_path=first_state,
        login="octocat",
    )[0]
    second = entitlement.bind_layer_decisions(
        [second_layer],
        [second_decision],
        state_path=second_state,
        login="octocat",
    )[0]

    release = context.Event()
    results = context.Queue()
    first_started = context.Event()
    first_process = context.Process(
        target=_binding_lease_process,
        args=([second.as_dict(), first.as_dict()], first_started, release, results, False),
    )
    first_process.start()
    assert first_started.wait(10)
    second_started = context.Event()
    second_process = context.Process(
        target=_binding_lease_process,
        args=([first.as_dict(), second.as_dict()], second_started, release, results, False),
    )
    second_process.start()
    assert not second_started.wait(0.2)
    release.set()
    first_process.join(10)
    second_process.join(10)
    assert (first_process.exitcode, second_process.exitcode) == (0, 0)
    assert {results.get(timeout=2), results.get(timeout=2)} == {
        (True, "committed")
    }

    crashed_started = context.Event()
    crashed = context.Process(
        target=_binding_lease_process,
        args=(
            [first.as_dict(), second.as_dict()],
            crashed_started,
            context.Event(),
            results,
            True,
        ),
    )
    crashed.start()
    assert crashed_started.wait(10)
    crashed.join(10)
    assert crashed.exitcode == 31
    valid, value = entitlement.run_under_binding_leases(
        (second, first), lambda: "recovered"
    )
    assert (valid, value) == (True, "recovered")


def test_protected_four_family_filter_has_one_fail_closed_contract(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    protected = [
        _layer(
            f"{product}-department",
            product=product,
            role="department",
            rank=20,
            path=tmp_path / product,
        )
        for product in ("claude", "codex", "cli", "knowledge")
    ]
    foundation = [
        _layer(
            f"{product}-foundation",
            product=product,
            role="foundation",
            rank=40,
            path=tmp_path / f"{product}-foundation",
            auth="anon",
        )
        for product in ("claude", "codex", "cli", "knowledge")
    ]
    personal = [
        _layer(
            f"{product}-personal",
            product=product,
            role="personal",
            rank=10,
            path=tmp_path / f"{product}-personal",
            auth="personal",
        )
        for product in ("claude", "codex", "cli", "knowledge")
    ]

    for layer in protected:
        assert _observe(layer, state, 200).eligible
    eligible, decisions = entitlement.filter_eligible_layers(
        protected + personal + foundation,
        state_path=state,
        login="octocat",
        now=NOW + timedelta(hours=1),
    )
    assert {layer["id"] for layer in eligible} == {
        layer["id"] for layer in protected + personal + foundation
    }
    assert len(decisions) == 12

    for layer in protected:
        _observe(layer, state, 404, now=NOW + timedelta(hours=2))
    eligible, decisions = entitlement.filter_eligible_layers(
        protected + personal + foundation,
        state_path=state,
        login="octocat",
        now=NOW + timedelta(hours=3),
    )
    assert {layer["id"] for layer in eligible} == {
        layer["id"] for layer in personal + foundation
    }
    assert {item.state for item in decisions if not item.eligible} == {"revoked"}


def test_revocation_replaces_protected_material_and_removes_stale_lock_pin(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    org = tmp_path / "org"
    foundation = tmp_path / "foundation"
    _write(org, "commands/protocol.md", "protected organization protocol\n")
    _write(foundation, "commands/protocol.md", "public foundation protocol\n")
    layers = [
        _layer(
            "claude-organization",
            product="claude",
            role="organization",
            rank=30,
            path=org,
        ),
        _layer(
            "claude-foundation",
            product="claude",
            role="foundation",
            rank=40,
            path=foundation,
            auth="anon",
        ),
    ]
    lock_path = tmp_path / "copilot.lock.json"
    output = tmp_path / "materialized"

    first = build_update_report(
        _layers=layers,
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=output,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
        _entitlement_login="octocat",
        _entitlement_token="fixture",
        _entitlement_get_json=lambda _url, _token: 200,
        _entitlement_state_path=state,
        _entitlement_now=NOW,
    )
    assert first["result"] == "applied"
    assert (output / "commands/protocol.md").read_text() == (
        "protected organization protocol\n"
    )
    assert "claude-organization" in json.loads(lock_path.read_text())

    previous = json.loads(lock_path.read_text())
    revoked = build_update_report(
        _layers=layers,
        _previous_lock=previous,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=output,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
        _entitlement_login="octocat",
        _entitlement_token="fixture",
        _entitlement_get_json=lambda _url, _token: 404,
        _entitlement_state_path=state,
        _entitlement_now=NOW + timedelta(hours=1),
    )
    written = json.loads(lock_path.read_text())
    assert revoked["result"] == "blocked"
    assert (output / "commands/protocol.md").read_text() == (
        "public foundation protocol\n"
    )
    assert "claude-organization" not in written
    assert "claude-foundation" in written
    assert any(
        item["dimension"] == "entitlement"
        and "organization-access-owner" in item["reason"]
        for item in revoked["blocked"]
    )


def test_revocation_never_destroys_customized_materialized_content(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    org = tmp_path / "org"
    _write(org, "commands/protocol.md", "protected organization protocol\n")
    layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=org,
    )
    lock_path = tmp_path / "copilot.lock.json"
    output = tmp_path / "materialized"
    build_update_report(
        _layers=[layer],
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=output,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
        _entitlement_login="octocat",
        _entitlement_token="fixture",
        _entitlement_get_json=lambda _url, _token: 200,
        _entitlement_state_path=state,
        _entitlement_now=NOW,
    )
    target = output / "commands/protocol.md"
    target.write_text("human customization\n", encoding="utf-8")
    previous = json.loads(lock_path.read_text())

    revoked = build_update_report(
        _layers=[layer],
        _previous_lock=previous,
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=output,
        _lock_write_path=lock_path,
        _policy=permissive_policy,
        _entitlement_login="octocat",
        _entitlement_token="fixture",
        _entitlement_get_json=lambda _url, _token: 404,
        _entitlement_state_path=state,
        _entitlement_now=NOW + timedelta(hours=1),
    )
    assert target.read_text() == "human customization\n"
    assert revoked["held_for_approval"]


def test_stale_protected_claude_cache_cannot_win_project_resolution(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    org = tmp_path / "org"
    foundation = tmp_path / "foundation"
    _write(org, "commands/protocol.md", "protected organization protocol\n")
    _write(
        foundation / ".claude",
        "commands/protocol.md",
        "public foundation protocol\n",
    )
    org_layer = _layer(
        "claude-organization",
        product="claude",
        role="organization",
        rank=30,
        path=org,
    )
    foundation_layer = _layer(
        "claude-foundation",
        product="claude",
        role="foundation",
        rank=40,
        path=foundation / ".claude",
        auth="anon",
    )
    _observe(org_layer, state, 200, now=NOW)

    entitled = resolve_claude_content(
        foundation_root=foundation,
        items={"commands": ("protocol",)},
        _layers=[org_layer, foundation_layer],
        entitlement_state_path=state,
        entitlement_login="octocat",
        entitlement_now=NOW + timedelta(hours=1),
    )
    assert entitled[("commands", "protocol")].layer == "claude-organization"

    stale = resolve_claude_content(
        foundation_root=foundation,
        items={"commands": ("protocol",)},
        _layers=[org_layer, foundation_layer],
        entitlement_state_path=state,
        entitlement_login="octocat",
        entitlement_now=NOW + timedelta(hours=73),
    )
    assert stale[("commands", "protocol")].layer == "claude-foundation"


def test_entitlement_state_symlink_or_identity_change_never_authorizes_cache(
    tmp_path: Path,
) -> None:
    layer = _layer(
        "knowledge-department",
        product="knowledge",
        role="department",
        rank=20,
        path=tmp_path / "knowledge",
    )
    real = tmp_path / "real.json"
    real.write_text(
        json.dumps({"schema_version": "1.0", "layers": {}}), encoding="utf-8"
    )
    state = tmp_path / "entitlements.json"
    state.symlink_to(real)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer], state_path=state, login="octocat", now=NOW
    )
    assert eligible == []
    assert decisions[0].state == "offline-unverified"

    state.unlink()
    _observe(layer, state, 200)
    eligible, decisions = entitlement.filter_eligible_layers(
        [layer], state_path=state, login="different-user", now=NOW
    )
    assert eligible == []
    assert decisions[0].state == "offline-unverified"


def test_revocation_removes_external_cli_and_knowledge_lock_authority(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state" / "entitlements.json"
    layers = [
        _layer(
            "cli-department",
            product="cli",
            role="department",
            rank=20,
            path=tmp_path / "cli-cache",
        ),
        _layer(
            "knowledge-department",
            product="knowledge",
            role="department",
            rank=20,
            path=tmp_path / "knowledge-cache",
        ),
    ]
    for layer in layers:
        Path(layer["source"]["path"]).mkdir(parents=True)
    lock_path = tmp_path / "copilot.lock.json"
    common = {
        "_layers": layers,
        "_mirror_root": tmp_path / "mirrors",
        "_materialize_root": tmp_path / "materialized",
        "_lock_write_path": lock_path,
        "_policy": permissive_policy,
        "_personal_roots": [],
        "_entitlement_login": "octocat",
        "_entitlement_token": "fixture",
        "_entitlement_state_path": state,
    }

    entitled = build_update_report(
        _previous_lock={},
        _entitlement_get_json=lambda _url, _token: 200,
        _entitlement_now=NOW,
        **common,
    )
    previous = json.loads(lock_path.read_text())
    # External products do not write this materialize root; their effective
    # layer authority is represented by lock metadata.
    assert entitled["result"] == "up-to-date"
    assert set(previous) == {"cli-department", "knowledge-department"}
    assert previous["cli-department"]["_meta"]["product"] == "cli"
    assert previous["knowledge-department"]["_meta"]["product"] == "knowledge"

    revoked = build_update_report(
        _previous_lock=previous,
        _entitlement_get_json=lambda _url, _token: 404,
        _entitlement_now=NOW + timedelta(hours=1),
        **common,
    )
    assert revoked["result"] == "blocked"
    assert json.loads(lock_path.read_text()) == {}
    assert {item["product"] for item in revoked["blocked"]} == {
        "cli",
        "knowledge",
    }
    # Revocation removes consumer authority, not the disposable mirror/cache.
    assert all(Path(layer["source"]["path"]).is_dir() for layer in layers)


def test_already_joined_layer_cannot_mask_a_live_revocation(tmp_path: Path) -> None:
    state = tmp_path / "state" / "entitlements.json"
    department = {
        "id": "finance",
        "name": "Finance",
        "repo": "fixture-org/finance",
        "product": "claude",
        "role": "department",
        "rank": 20,
        "auth": "work",
    }
    joined = _layer(
        "finance",
        product="claude",
        role="department",
        rank=20,
        path=tmp_path / "cache",
    )
    _observe(joined, state, 200)

    report = build_layers_join_report(
        "finance",
        _identity={"login": "octocat"},
        _get_secret=lambda login, *, service: (
            "fixture"
            if login == "octocat" and service == GITHUB_KEYCHAIN_SERVICE
            else None
        ),
        _departments=[department],
        _layers=[joined],
        _get_json=lambda _url, _token: 404,
        _entitlement_state_path=state,
        _entitlement_now=NOW + timedelta(hours=1),
    )
    assert report["result"] == "not-entitled"
    assert "revoked" in report["reason"]
    assert "organization-access-owner" in report["reason"]


def test_public_only_update_does_not_consult_identity_or_keychain(
    tmp_path: Path, monkeypatch
) -> None:
    foundation = tmp_path / "foundation"
    _write(foundation, "commands/protocol.md", "public\n")
    layer = _layer(
        "claude-foundation",
        product="claude",
        role="foundation",
        rank=40,
        path=foundation,
        auth="anon",
    )

    def forbidden() -> None:
        raise AssertionError("public update consulted protected identity state")

    monkeypatch.setattr(entitlement, "current_login", forbidden)
    monkeypatch.setattr("cc.core.ecosystem.mirror.resolve_token", forbidden)
    report = build_update_report(
        _layers=[layer],
        _previous_lock={},
        _mirror_root=tmp_path / "mirrors",
        _materialize_root=tmp_path / "materialized",
        _lock_write_path=tmp_path / "lock.json",
        _policy=permissive_policy,
        _personal_roots=[],
    )
    assert report["result"] == "applied"
