"""Item 2: the reversible settings-mutation ledger.

Covers the pure JSON merge/removal contract (no filesystem) and the full
`project_lock` + `SnapshotVault` transaction (apply / idempotent re-apply /
surgical remove / byte-exact rollback / conflict detection / interrupted-
write recovery / backward compatibility with a `mutations[]`-less lock).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from cc.core.ecosystem.mutations import (
    DEFAULT_HOOK_ENTRIES,
    HookEntrySpec,
    apply_settings_hook,
    list_sources,
    merge_hook_entries,
    read_mutations,
    remove_hook_entries,
    remove_settings_hook,
    rollback_settings_hook,
    spec_fingerprint,
)
from cc.core.ecosystem.project_locking import project_lock
from cc.core.ecosystem.projects import read_project_lock


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(("git", "init", "-q"), cwd=path, check=True)
    return path


def _canonical(document: dict) -> str:
    return json.dumps(document, indent=2)


# ---------------------------------------------------------------------------
# Pure merge/removal contract -- no filesystem.
# ---------------------------------------------------------------------------


def test_merge_preserves_sibling_keys_and_foreign_hook_groups_convoco_shape():
    convoco = {
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {
                            "command": "/repos/convoco/.claude/hooks/discord-stop.sh",
                            "timeout": 604800,
                            "type": "command",
                        }
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "command": "/repos/convoco/.claude/hooks/discord-user-prompt-submit.sh",
                            "timeout": 30,
                            "type": "command",
                        }
                    ]
                }
            ],
        }
    }

    merged, actions = merge_hook_entries(convoco, DEFAULT_HOOK_ENTRIES, source="claude-copilot")

    # The foreign Stop event is untouched byte-for-byte.
    assert merged["hooks"]["Stop"] == convoco["hooks"]["Stop"]

    # Convoco's own UserPromptSubmit group survives, unmodified, alongside a
    # NEW group for ours -- never merged into, never replaced.
    up = merged["hooks"]["UserPromptSubmit"]
    assert len(up) == 2
    assert convoco["hooks"]["UserPromptSubmit"][0] in up
    ours = [g for g in up if g["hooks"][0].get("_copilot_source") == "claude-copilot"]
    assert len(ours) == 1

    assert {a.action for a in actions} == {"added"}


def test_user_pretooluse_entry_survives_alongside_framework_entry():
    user_settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Write",
                    "hooks": [{"type": "command", "command": "/my/own/guard.sh"}],
                }
            ]
        }
    }
    merged, _ = merge_hook_entries(user_settings, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
    groups = merged["hooks"]["PreToolUse"]
    assert len(groups) == 2
    assert groups[0] == user_settings["hooks"]["PreToolUse"][0]
    assert groups[1]["matcher"] == "Bash|Read|Edit|Write|Agent"
    assert groups[1]["hooks"][0]["_copilot_source"] == "claude-copilot"


def test_sibling_settings_keys_are_never_touched():
    settings = {
        "permissions": {"allow": ["Bash(git *)"]},
        "statusLine": {"type": "command", "command": "~/.claude/statusline.sh"},
        "enabledMcpjsonServers": ["figma"],
        "theme": "dark",
    }
    merged, _ = merge_hook_entries(settings, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
    for key in ("permissions", "statusLine", "enabledMcpjsonServers", "theme"):
        assert merged[key] == settings[key]


def test_merge_hook_entries_is_idempotent():
    once, once_actions = merge_hook_entries({}, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
    twice, twice_actions = merge_hook_entries(once, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
    assert twice == once
    assert {a.action for a in once_actions} == {"added"}
    assert {a.action for a in twice_actions} == {"unchanged"}


def test_round_trip_remove_of_add_is_byte_identical_for_a_settings_corpus():
    corpus = [
        {},
        {"permissions": {"allow": []}},
        {
            "hooks": {
                "UserPromptSubmit": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/user-prompt-protocol.sh"',
                            }
                        ],
                    }
                ],
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write",
                        "hooks": [
                            {
                                "type": "command",
                                "command": 'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/post-edit-verify.sh"',
                            }
                        ],
                    }
                ],
            }
        },
        {
            "hooks": {
                "Stop": [
                    {
                        "hooks": [
                            {
                                "command": "/x/discord-stop.sh",
                                "timeout": 604800,
                                "type": "command",
                            }
                        ]
                    }
                ]
            }
        },
        {"enabledMcpjsonServers": ["figma"]},
    ]
    for fixture in corpus:
        added, _ = merge_hook_entries(fixture, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
        removal = remove_hook_entries(added, DEFAULT_HOOK_ENTRIES)
        assert _canonical(removal.settings) == _canonical(fixture), fixture
        assert removal.not_found == ()


def test_remove_only_matches_exact_fingerprint_never_position_or_name():
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|Read|Edit|Write|Agent",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/a/different/command.sh",
                            "_copilot_source": "someone-else",
                        }
                    ],
                }
            ]
        }
    }
    entries = (DEFAULT_HOOK_ENTRIES[1],)  # PreToolUse
    removal = remove_hook_entries(settings, entries)
    # Same event+matcher, different command -> different fingerprint -> untouched.
    assert removal.settings == settings
    assert removal.removed == ()
    assert removal.not_found == (entries[0].fingerprint(),)


# ---------------------------------------------------------------------------
# Full transaction: project_lock + SnapshotVault, real filesystem.
# ---------------------------------------------------------------------------


def test_apply_is_idempotent_second_apply_is_unchanged_not_a_duplicate(tmp_path):
    project = _repo(tmp_path / "project")
    state_root = tmp_path / "state"

    first = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES,
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    assert first.status == "applied"
    settings_path = project / ".claude" / "settings.json"
    first_bytes = settings_path.read_bytes()
    lock_after_first = read_project_lock(project / "copilot.lock.json")
    assert len(read_mutations(lock_after_first)) == 1

    second = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES,
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    assert second.status == "unchanged"
    assert settings_path.read_bytes() == first_bytes
    lock_after_second = read_project_lock(project / "copilot.lock.json")
    assert len(read_mutations(lock_after_second)) == 1
    assert lock_after_second == lock_after_first


def test_rollback_is_byte_exact_and_restores_the_untouched_original(tmp_path):
    project = _repo(tmp_path / "project")
    (project / ".claude").mkdir()
    original = '{\n  "permissions": {\n    "allow": [\n      "Bash"\n    ]\n  }\n}\n'
    (project / ".claude" / "settings.json").write_text(original, encoding="utf-8")
    state_root = tmp_path / "state"

    outcome = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES,
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    assert outcome.status == "applied"
    mutation_id = outcome.mutation["id"]
    assert (project / ".claude" / "settings.json").read_text(encoding="utf-8") != original

    result = rollback_settings_hook(project, mutation_id=mutation_id, _state_root=state_root)
    assert result.status == "restored"
    assert (project / ".claude" / "settings.json").read_text(encoding="utf-8") == original

    lock = read_project_lock(project / "copilot.lock.json")
    assert read_mutations(lock) == []


def test_rollback_refuses_and_leaves_the_file_untouched_after_a_user_edit(tmp_path):
    project = _repo(tmp_path / "project")
    state_root = tmp_path / "state"

    outcome = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES[:1],
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    mutation_id = outcome.mutation["id"]

    settings_path = project / ".claude" / "settings.json"
    live = json.loads(settings_path.read_text(encoding="utf-8"))
    live["permissions"] = {"allow": ["Read"]}
    settings_path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    edited_bytes = settings_path.read_bytes()

    result = rollback_settings_hook(project, mutation_id=mutation_id, _state_root=state_root)
    assert result.status == "conflict"
    assert settings_path.read_bytes() == edited_bytes

    # The ledger row is untouched too -- refusing means refusing, not a
    # partial revert.
    lock = read_project_lock(project / "copilot.lock.json")
    assert len(read_mutations(lock)) == 1
    assert read_mutations(lock)[0]["id"] == mutation_id


def test_remove_is_surgical_and_reverting_twice_is_safe(tmp_path):
    project = _repo(tmp_path / "project")
    state_root = tmp_path / "state"

    outcome = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES,
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    mutation_id = outcome.mutation["id"]

    first = remove_settings_hook(project, mutation_id=mutation_id, _state_root=state_root)
    assert first.status == "removed"
    assert not (project / ".claude" / "settings.json").exists()
    lock = read_project_lock(project / "copilot.lock.json")
    assert read_mutations(lock) == []

    second = remove_settings_hook(project, mutation_id=mutation_id, _state_root=state_root)
    assert second.status == "not-found"


def test_remove_preserves_a_foreign_group_with_the_same_event_and_matcher(tmp_path):
    project = _repo(tmp_path / "project")
    (project / ".claude").mkdir()
    (project / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {"hooks": [{"type": "command", "command": "/human/own-hook.sh"}]}
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    state_root = tmp_path / "state"

    outcome = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES[3:4],  # UserPromptSubmit only
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    mutation_id = outcome.mutation["id"]

    result = remove_settings_hook(project, mutation_id=mutation_id, _state_root=state_root)
    assert result.status == "removed"
    settings = json.loads((project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["UserPromptSubmit"] == [
        {"hooks": [{"type": "command", "command": "/human/own-hook.sh"}]}
    ]


def test_interrupted_write_between_settings_and_ledger_leaves_a_valid_file_and_is_detected(
    tmp_path,
):
    project = _repo(tmp_path / "project")
    state_root = tmp_path / "state"
    entries = DEFAULT_HOOK_ENTRIES[:1]

    # Simulate the exact crash window the module docstring names: the
    # settings write completes (atomic, so the file is always valid) but
    # the process dies before the ledger row is ever written.
    with project_lock(project, lock_root=state_root / "locks") as anchored:
        merged, _ = merge_hook_entries({}, entries, source="claude-copilot")
        anchored.atomic_write(
            ".claude/settings.json", (json.dumps(merged, indent=2) + "\n").encode("utf-8")
        )

    settings_path = project / ".claude" / "settings.json"
    assert settings_path.exists()
    # The file must be valid, parseable JSON -- never half-written.
    parsed = json.loads(settings_path.read_text(encoding="utf-8"))
    assert parsed == merged

    lock = read_project_lock(project / "copilot.lock.json")
    assert read_mutations(lock) == []  # no ledger row -- the crash window

    report = list_sources(project, _state_root=state_root)
    orphaned = [row for row in report["hooks"] if row["classification"] == "orphaned"]
    assert len(orphaned) == 1
    assert orphaned[0]["event"] == entries[0].event
    assert orphaned[0]["mutation_id"] is None


def test_old_lock_without_mutations_key_still_loads_and_is_untouched_by_a_new_mutation(
    tmp_path,
):
    project = _repo(tmp_path / "project")
    old_lock = {
        "schema_version": "1.0",
        "components": [
            {
                "component": "claude",
                "version": "2.12.0",
                "release_tag": "v2.12.0",
                "files": [
                    {
                        "path": ".claude/fitness-check.sh",
                        "ownership": "framework",
                        "checksum": "sha256:" + "0" * 64,
                    }
                ],
            }
        ],
    }
    (project / "copilot.lock.json").write_text(
        json.dumps(old_lock, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Backward compatibility: a 46-project-style lock with no mutations[]
    # key reads exactly as "nothing has been mutated yet".
    loaded = read_project_lock(project / "copilot.lock.json")
    assert read_mutations(loaded) == []
    assert loaded["components"] == old_lock["components"]

    state_root = tmp_path / "state"
    outcome = apply_settings_hook(
        project,
        entries=DEFAULT_HOOK_ENTRIES[:1],
        source="claude-copilot",
        component="claude",
        applied_by="test",
        _state_root=state_root,
    )
    assert outcome.status == "applied"

    new_lock = read_project_lock(project / "copilot.lock.json")
    # schema_version is deliberately never bumped -- project_integration.py's
    # _lock_state() and project_migrations.py both hard-require an EXACT
    # "1.0" match; bumping it would make this project's lock "unreadable"
    # to both. See mutations.py's module docstring.
    assert new_lock["schema_version"] == "1.0"
    assert new_lock["components"] == old_lock["components"]
    assert len(read_mutations(new_lock)) == 1


def test_spec_fingerprint_is_stable_and_order_sensitive():
    a = spec_fingerprint("PreToolUse", "Bash", "echo hi")
    b = spec_fingerprint("PreToolUse", "Bash", "echo hi")
    c = spec_fingerprint("PreToolUse", "Bash", "echo bye")
    assert a == b
    assert a != c
    assert a.startswith("sha256:")


def test_hook_entry_spec_as_dict_round_trips_the_fingerprint():
    entry = HookEntrySpec("PreToolUse", "Bash", "echo hi")
    data = entry.as_dict()
    assert data["spec_fingerprint"] == entry.fingerprint()
    assert data["event"] == "PreToolUse"
