# Skills Authoring Guide

**Diátaxis mode:** How-to + Reference

This guide explains how to author Claude Copilot skills — both prose-only skills and code-bearing skills with L1/L2/L3 structure. It graduates the conversion recipe in `SKILLS-ROLLOUT.md` into permanent documentation.

For the live conversion queue and completion status, see [`SKILLS-ROLLOUT.md`](../../SKILLS-ROLLOUT.md).

---

## Prerequisites

- Python 3.9+, pytest (`pip install pytest`)
- Familiarity with the `cc skill` CLI (`cc skill list`, `cc skill get <name>`)
- A clear problem to encode: something the model currently re-derives from scratch every session

---

## Two Skill Patterns

| Pattern | When to Use |
|---------|-------------|
| **Prose-only (L1 + L2)** | When quality requires judgment, context, or taste — no closed rule set |
| **Code-bearing (L1 + L2 + L3)** | When a deterministic core exists: arithmetic, table lookups, structural validation, coverage checking |

**The key question:** "Is there logic here that the model re-derives every session, where re-derivation is error-prone and a script would always get it right?" If yes, add a script. If not, keep it prose.

### Prose-Legit (Do NOT Convert)

Some skills have no genuine deterministic core. Converting them would produce fake scripts. Known prose-legit skills include:
- Copywriting/voice and tone (subjective, generative)
- Design aesthetics, color palettes, typographic harmony (taste)
- Tutorial pedagogy (Diátaxis judgment)
- Any "is this good?" evaluation

---

## L1 / L2 / L3 Structure

```
.claude/skills/<category>/<skill-name>/
  SKILL.md                # L1 frontmatter + L2 prose + Invocation section
  scripts/<name>.py       # L3 executable (Python stdlib only)
  scripts/test_<name>.py  # pytest test suite
  templates/              # optional output scaffolds
```

### L1 — Frontmatter

The YAML frontmatter in SKILL.md controls auto-firing and tooling. The canonical target shape:

```yaml
---
name: stride-dread
description: >-
  STRIDE threat enumeration and DREAD severity scoring for security reviews.
  Covers auth, authorization, session management, PII handling, and API design.
  Use proactively when reviewing authentication flows, designing APIs that
  handle PII, performing threat modeling, or running security-critical code
  review. Run the DREAD scorer for deterministic severity bands.
version: 2.0.0
allowed-tools: [Read, Grep, Glob, Bash]   # required for code-bearing scripts
---
```

Key fields:
- `name`: Always use `name` (not `skill_name` — that field does not exist in any skill file).
- `description`: **This is the primary auto-firing trigger surface.** Write a multi-sentence, trigger-rich description ending in "Use proactively when..." that folds in all the trigger phrases that should activate this skill. Native Claude Code surfaces `name` + `description` into the model's available-skills context; the model fires the skill automatically when a prompt matches.
- `version`: Use `1.0.0` for prose-only, `2.0.0` for code-bearing.
- `allowed-tools`: Include `Bash` if the skill has a script. Required for the execution path.
- `when_to_use`, `trigger_keywords`, `trigger_files`: These legacy fields are harmless if present (native Claude Code ignores unknown YAML keys) but are no longer the discovery mechanism. They can be removed from new skills; existing skills need not be edited solely to remove them.
- `cc skill search` is a **case-insensitive substring match** over `name + description + tags`. It is NOT FTS5 full-text search. It serves as a **fallback** for agents (especially subagents that do not receive hook-injected context) and for explicit lookup. More descriptive text in `description` improves both auto-firing and substring discoverability.

### L2 — Prose

The human-readable methodology. Write this first — the prose is the primary artifact. The script only handles the deterministic subset. L2 should contain:
- When to use this skill
- The methodology (frameworks, standards, anti-patterns)
- Judgment guidance the model needs
- Examples of good and bad outputs

### L3 — Script

An executable that handles exactly the deterministic core, nothing more.

---

## Script Rules (L3)

### Rule 1 — Python stdlib only

No `pip install`. Allowed: `json`, `sys`, `argparse`, `re`, `pathlib`, `ast`, `subprocess`. No `requests`, `pydantic`, `numpy`, etc.

### Rule 2 — File-path or stdin input

First argument is a path, OR `'-'` / no argument reads stdin:

```python
import sys, json, argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", nargs="?", default="-",
                        help="Path to input file, or '-' for stdin")
    args = parser.parse_args()

    if args.input == "-":
        data = json.load(sys.stdin)
    else:
        with open(args.input) as f:
            data = json.load(f)
    # ...
```

### Rule 3 — Validate all inputs

Unknown values, wrong types, out-of-range numbers: print to stderr, exit 1.

```python
if not isinstance(data.get("findings"), list):
    print("ERROR: 'findings' must be a list", file=sys.stderr)
    sys.exit(1)
```

### Rule 4 — Structured output: JSON first, then markdown

Both go to stdout:

```python
import json

result = {"score": 7.2, "band": "HIGH", "gaps": ["T-Tampering"]}

print("```json")
print(json.dumps(result, indent=2))
print("```")
print()
print(f"## Result\n\n**Score:** {result['score']} — {result['band']}")
```

### Rule 5 — No voodoo constants

Every threshold, band boundary, or minimum value must be a named constant with a cited standard:

```python
# DREAD scoring bands — per OWASP DREAD methodology (owasp.org/www-community/DREAD)
DREAD_BAND_CRITICAL = 9.0   # 9.0 – 10.0
DREAD_BAND_HIGH     = 7.0   # 7.0 – 8.9
DREAD_BAND_MEDIUM   = 4.0   # 4.0 – 6.9
DREAD_BAND_LOW      = 0.0   # 0.0 – 3.9
```

### Rule 6 — Exit codes

| Exit code | Meaning |
|-----------|---------|
| 0 | Success (even if findings are bad — the script classifies, the agent decides) |
| 1 | Invalid input (bad JSON, missing required fields, out-of-range values) |

Empty input is not an error: return an empty-findings structure, exit 0.

---

## SKILL.md Invocation Section

Every code-bearing SKILL.md must include an **Invocation** section explaining how to run the script:

```markdown
## Invocation

Run the script to get a structured analysis. Consume the **output only** — the script source never enters context.

### Input format

```json
{
  "findings": [
    {
      "category": "T",
      "description": "Attacker can forge session tokens",
      "score": {"D": 8, "R": 6, "E": 7, "A": 9, "D2": 8}
    }
  ]
}
```

### Run

```bash
# From file
python .claude/skills/security/stride-dread/scripts/dread_score.py input.json

# From stdin
python .claude/skills/security/stride-dread/scripts/dread_score.py - <<'EOF'
{ "findings": [...] }
EOF
```

### Output

JSON block (machine-readable) followed by a markdown summary (human-readable). Fields:
- `score`: DREAD average (0–10)
- `band`: CRITICAL / HIGH / MEDIUM / LOW
- `gaps`: STRIDE categories with zero findings

**What to do with results:** Use `band` and `gaps` to prioritize follow-up. Do not block on score alone — context matters.

### Error handling

Exit 1 + stderr message on invalid input. Correct the input and re-run.
```

---

## pytest Test Suite

Tests go in `scripts/test_<name>.py`. Cover:

1. **Named constants at their boundaries** — each band threshold, each key size minimum
2. **Each invalid-input path** — exits non-zero, error on stderr
3. **Each valid-input path** — exits 0
4. **stdin (`-`) and file-path** — both parse correctly
5. **Empty input** — exits 0 with empty-findings structure
6. **Output structure** — JSON block present, markdown section present
7. **Sort/ranking order** where applicable

### Test example skeleton

```python
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent / "dread_score.py"

def run(input_data, use_stdin=True):
    if use_stdin:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "-"],
            input=json.dumps(input_data),
            capture_output=True,
            text=True,
        )
    else:
        import tempfile, os
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(input_data, f)
            fname = f.name
        result = subprocess.run([sys.executable, str(SCRIPT), fname],
                                capture_output=True, text=True)
        os.unlink(fname)
    return result

def test_valid_single_finding_stdin():
    data = {"findings": [{"category": "T", "description": "x",
                           "score": {"D": 8, "R": 6, "E": 7, "A": 9, "D2": 8}}]}
    r = run(data)
    assert r.returncode == 0
    assert "json" in r.stdout

def test_empty_input_exits_zero():
    r = run({"findings": []})
    assert r.returncode == 0

def test_invalid_input_exits_one():
    r = run({"findings": "not-a-list"})
    assert r.returncode == 1
    assert "ERROR" in r.stderr

def test_high_band_boundary():
    # Score 9.0 is CRITICAL, 8.9 is HIGH
    # (test with actual boundary data)
    pass
```

---

## Step-by-Step Recipe

1. **Identify the deterministic core** — arithmetic, table lookups, structural validation, coverage checking. If none exists, keep the skill prose-only.
2. **Plan the directory layout** — `scripts/<name>.py` + `scripts/test_<name>.py`.
3. **Write the script** — stdlib only, file-path/stdin, structured output, named constants with citations.
4. **Update SKILL.md** — bump version to `2.0.0`, add `allowed-tools: [Read, Grep, Glob, Bash]`, add Invocation section.
5. **Write pytest tests** — boundaries, invalid inputs, valid inputs, stdin + file, empty input, output structure.
6. **Run and verify:**
   ```bash
   python .claude/skills/<category>/<name>/scripts/<name>.py - <<'EOF'
   { "findings": [] }
   EOF

   python -m pytest .claude/skills/<category>/<name>/scripts/test_<name>.py -v
   ```
7. **Register with cc CLI:**
   ```bash
   # Skills in .claude/skills/ are auto-discovered by cc skill list
   cc skill list | grep <name>
   ```

---

## Current Skill Roster

16 code-bearing skills have been converted. See `SKILLS-ROLLOUT.md` for the full table with status, batch, and script names.

| Category | Skills |
|----------|--------|
| Security | stride-dread, threat-modeling, web-security, crypto-patterns |
| Testing | pytest-patterns, jest-patterns |
| Languages/Code | refactoring-patterns, python-idioms, javascript-patterns, react-patterns |
| DevOps | docker-patterns, kubernetes, ci-cd-patterns, git-workflows |
| Docs/Architecture | api-docs, system-design-patterns |
| Sales (vertical) | copilot-fireflies (call notes → CRM fields), copilot-crm (deal hygiene, pipeline review) — wired to `@agent-cs` |

---

## Prose-Legit Skills (do NOT convert)

These skills have been evaluated and confirmed to have no genuine deterministic core. See `SKILLS-ROLLOUT.md` for the full list and reasoning.

Examples: `copywriting/litmus-test`, `design/aesthetic-directions`, `documentation/tutorial-patterns`.

---

## Related

- [`SKILLS-ROLLOUT.md`](../../SKILLS-ROLLOUT.md) — the live conversion queue and rollout record
- [`cc skill list`](../20-configuration/01-configuration.md) — discover installed skills
- [References Registry](../20-configuration/03-references-registry.md) — register stable paths for skill invocation
