"""cc rule: rewrite-in-place, section insert, date suffix, log, propose."""

import json

from cc.main import app

BOOK = """# Rules

## Stack

- Use Next.js.
- Never recommend Salesforce.

## Autonomy

Intro line.

## Empty
"""


def _book(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text(BOOK)
    return f


def _add(runner, f, *args):
    return runner.invoke(app, ["rule", "add", "--file", str(f), "--date", "2026-10-29", *args])


def test_replace_keeps_bullet_and_adds_date(runner, tmp_path):
    f = _book(tmp_path)
    r = _add(runner, f, "--text", "CRM is Pipeline Copilot.", "--replaces", "Salesforce")
    assert r.exit_code == 0, r.output
    lines = f.read_text().split("\n")
    assert "- CRM is Pipeline Copilot. (2026-10-29)" in lines
    assert not any("Salesforce" in line for line in lines)
    assert len(lines) == len(BOOK.split("\n"))


def test_existing_date_is_not_doubled(runner, tmp_path):
    f = _book(tmp_path)
    _add(runner, f, "--text", "Use Remix. (2026-01-02)", "--replaces", "Next.js")
    assert "- Use Remix. (2026-01-02)" in f.read_text()
    assert "(2026-10-29)" not in f.read_text()


def test_replace_errors_on_zero_and_many(runner, tmp_path):
    f = _book(tmp_path)
    assert _add(runner, f, "--text", "x", "--replaces", "nothing here").exit_code == 1
    many = _add(runner, f, "--text", "x", "--replaces", "e", "--json")
    assert many.exit_code == 1 and "matched" in json.loads(many.output)["error"]
    assert f.read_text() == BOOK


def test_section_insert_is_last_bullet(runner, tmp_path):
    f = _book(tmp_path)
    assert _add(runner, f, "--text", "Use Python.", "--section", "Stack").exit_code == 0
    lines = f.read_text().split("\n")
    i = lines.index("- Never recommend Salesforce.")
    assert lines[i + 1] == "- Use Python. (2026-10-29)"


def test_section_without_bullets_and_missing_heading(runner, tmp_path):
    f = _book(tmp_path)
    assert _add(runner, f, "--text", "A.", "--section", "## Empty").exit_code == 0
    assert f.read_text().rstrip("\n").endswith("- A. (2026-10-29)")
    assert _add(runner, f, "--text", "A.", "--section", "Nope").exit_code == 1


def test_neither_replaces_nor_section_is_an_error(runner, tmp_path):
    f = _book(tmp_path)
    r = _add(runner, f, "--text", "A.")
    assert r.exit_code == 1 and f.read_text() == BOOK


def test_dry_run_writes_and_logs_nothing(runner, tmp_path):
    f = _book(tmp_path)
    r = _add(runner, f, "--text", "A.", "--section", "Stack", "--dry-run")
    assert r.exit_code == 0 and f.read_text() == BOOK
    assert json.loads(runner.invoke(app, ["rule", "list", "--json"]).output) == []


def test_log_and_list(runner, tmp_path):
    f = _book(tmp_path)
    _add(runner, f, "--text", "B.", "--replaces", "Salesforce")
    _add(runner, f, "--text", "C.", "--section", "Stack")
    rows = json.loads(runner.invoke(app, ["rule", "list", "--json"]).output)
    assert len(rows) == 2
    assert set(rows[0]) == {"recordedAt", "destination", "file", "section", "replaced", "text"}
    assert rows[0]["replaced"] == "- Never recommend Salesforce." and rows[0]["section"] == "Stack"
    assert json.loads(runner.invoke(app, ["rule", "list", "--since", "2999-01-01", "--json"]).output) == []
    assert "C. (2026-10-29)" in runner.invoke(app, ["rule", "list"]).output


def test_framework_needs_file_and_resolves_relative(runner, tmp_path, monkeypatch):
    assert runner.invoke(app, ["rule", "add", "--destination", "framework", "--text", "x", "--section", "S"]).exit_code == 1
    root = tmp_path / "fw"
    root.mkdir()
    (root / "A.md").write_text(BOOK)
    monkeypatch.setattr("cc.commands.rule._framework_root", lambda: root)
    r = runner.invoke(app, ["rule", "add", "--destination", "framework", "--file", "A.md", "--text", "Y.", "--section", "Stack"])
    assert r.exit_code == 0, r.output
    assert "Y." in (root / "A.md").read_text()


def test_memory_destination_stores_lesson(runner):
    r = runner.invoke(app, ["rule", "add", "--destination", "memory", "--text", "Infisical prod /shared holds keys.", "--json"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["ok"] and out["text"].endswith("(" + out["text"][-11:-1] + ")")
    listed = json.loads(runner.invoke(app, ["memory", "list", "--type", "lesson", "--scope", "global", "--json"]).output)
    assert listed


def test_propose_heuristics(runner):
    def dest(text):
        return json.loads(runner.invoke(app, ["rule", "propose", "--text", text, "--json"]).output)["destination"]

    assert dest("The key is at Infisical prod") == "memory"
    assert dest("See https://example.com/doc") == "memory"
    assert dest("Always run the linter before commit") == "framework"
    assert dest("Always run the Convoco smoke test before deploy") == "project"
    assert dest("Prefer reversible methods") == "global"
    assert dest("Convoco prefers plain language") == "project"
    assert "Recommended destination: global" in runner.invoke(app, ["rule", "propose", "--text", "Prefer reversible methods"]).output
