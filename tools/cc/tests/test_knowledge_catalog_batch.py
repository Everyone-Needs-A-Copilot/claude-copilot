"""A CLI catalog operation retains its authenticated Knowledge source batch."""

from pathlib import Path

import pytest

from cc.commands import skill as command
from cc.core import skill_store
from cc.core.ecosystem import knowledge_skill_source as authority


@pytest.mark.parametrize("scope", ["knowledge", "all"])
def test_catalog_resolves_once_and_reads_each_signed_source(tmp_path, monkeypatch, scope):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(skill_store, "_git_root", lambda: None)
    monkeypatch.setattr(skill_store, "_framework_skills_dir", lambda: None)
    monkeypatch.setattr(command, "_resolve_skill_cache_dir", lambda: tmp_path / "cache")
    calls = []
    reads = []

    class Source:
        def __init__(self, name):
            self.path = tmp_path / name / "SKILL.md"
            self.path.parent.mkdir()
            self.path.write_text("untrusted checkout content")

        def skill_files(self):
            return (self.path,)

        def read_text(self, path):
            assert path == self.path
            reads.append(path)
            return f"---\nname: {path.parent.name}\ndescription: Authenticated bytes\n---\n"

    first, second = Source("first"), Source("second")
    unsigned = tmp_path / "unsigned"
    unsigned.mkdir()
    (unsigned / "SKILL.md").write_text("---\nname: personal\ndescription: Explicit compatibility\n---\n")
    sources = [(first.path.parent, first), (second.path.parent, second), (unsigned, None)]

    def resolve():
        calls.append("resolve")
        return sources

    monkeypatch.setattr(authority, "resolve_knowledge_skill_sources", resolve)
    skills = command._load_all_skills(scope)
    assert calls == ["resolve"]
    assert reads == [first.path, second.path]
    assert [skill.name for skill in skills] == ["first", "second", "personal"]
    assert [skill.description for skill in skills[:2]] == ["Authenticated bytes"] * 2
    assert [skill._knowledge_source for skill in skills] == [first, second, None]


def test_catalog_authentication_failure_is_not_unsigned_fallback(monkeypatch):
    def reject():
        raise authority.KnowledgeSkillSourceError("signed tree does not match")

    monkeypatch.setattr(authority, "resolve_knowledge_skill_sources", reject)
    with pytest.raises(authority.KnowledgeSkillSourceError, match="signed tree does not match"):
        command._load_all_skills("knowledge")
