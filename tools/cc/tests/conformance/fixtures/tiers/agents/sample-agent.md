---
name: sample-agent
description: Synthetic agent fixture for test_layer1_tier.py's H-5 hermetic test. Not a real framework agent.
---

# Sample Agent

Fixture only. Shaped like a real framework agent's knowledge-consumption instructions so `extract_knowledge_alias_subpaths()` has realistic prose to parse against, without depending on this machine's real `cw.md`/`sd.md`/`ta.md`.

## Workflow

1. `eval "$(cc env)"` -- hydrate CC_SHARED_DOCS, CC_KNOWLEDGE_REPO, etc.
2. Consult `$CC_KNOWLEDGE_REPO/reference/style/` (writing conventions) and `$CC_KNOWLEDGE_REPO/reference/glossary.md` (defined terms) before drafting anything.
