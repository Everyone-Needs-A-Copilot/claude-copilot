"""Required names survive byte deduplication without duplicating context."""
from cc.core.skill_store import discover_skills_with_sources, select_skill_context


def test_required_aliases_preserve_identity_and_budget(tmp_path):
    for name in ('a', 'b'):
        d = tmp_path / name
        d.mkdir()
        (d / 'SKILL.md').write_text('---\ndescription: Same bytes\n---\nShared behavior\n')
    skills = discover_skills_with_sources([(tmp_path, 'project')])
    result = select_skill_context('', skills, required=('a', 'b'), max_chars=0)
    assert [r['name'] for r in result['selected']] == ['a', 'b']
    original, alias = result['selected']
    assert alias['required'] is True
    assert alias['duplicate_of'] == 'a'
    assert alias['content'] == ''
    assert alias['characters'] == alias['utf8_bytes'] == 0
    assert result['loaded_characters'] == len(original['content'])
    assert result['mandatory_over_budget'] is True
    assert result['excluded'] == []
    assert alias['source_revision'] == original['source_revision']
