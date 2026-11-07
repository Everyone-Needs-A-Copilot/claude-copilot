"""The fingerprint-keyed hook merge/removal contract (no filesystem).

The project transaction half (apply / remove / rollback against a `mutations[]` ledger in a
project's `copilot.lock.json`) was retired with the per-project copy model; the user-level
registration that replaced it is covered by tests/hook_shim/test_user_level_shim.py.
"""

from __future__ import annotations

import json

from cc.core.ecosystem.mutations import (
    HookEntrySpec,
    merge_hook_entries,
    remove_hook_entries,
    spec_fingerprint,
    user_hook_entries,
)

DEFAULT_HOOK_ENTRIES = user_hook_entries()


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


def test_default_entries_install_pre_compact_handoff():
    merged, _ = merge_hook_entries({}, DEFAULT_HOOK_ENTRIES, source="claude-copilot")
    commands = [h["command"] for g in merged["hooks"]["PreCompact"] for h in g["hooks"]]
    assert len(commands) == 1
    assert "copilot-hook.sh" in commands[0] and "pre-compact-handoff" in commands[0]
