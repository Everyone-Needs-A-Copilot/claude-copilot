# Work Product Type Allowlist

`tc wp store --type` is validated against `WP_VALID_TYPES` in `tools/tc/src/tc/services/wp.py`. An unrecognised type is rejected with a non-zero exit (`EXIT_VALIDATION`) and a message naming the offending value plus every valid type. This document records where the allowlist came from, so future additions are made the same evidence-based way rather than by guessing.

## Why this exists

Before this validation existed, `tc wp store --type` silently accepted any string. Agents probing the CLI for correct flag syntax created junk work-product rows with literal probe values (`INVALID`, `badtype`, `bogus`, `ZZZ`) in at least three independent projects (research-copilot, convoco, copilot-control-tower). Because this tool is shared machine-wide, a validation fix had to avoid the opposite failure mode — an incomplete allowlist silently breaking legitimate work-product storage in every other project.

## How the set was derived

The allowlist is the union of every distinct `type` value found across every `tasks.db` reachable on the machine at the time of the fix (roughly twenty projects under `/Volumes/Dev/Sites/COPILOT/` plus mirrored copies), minus a small set of values that read as literal probe/typo artifacts rather than intentional categorisation: `bogus`, `badtype`, `ZZZ`, and `INVALID` (the last already removed from research-copilot's live database by a prior cleanup, but excluded here on the same evidence). Every type explicitly named in the framework's own agent instructions (`architecture`, `implementation`, `test-plan`, `documentation`, `specification`, `infrastructure`, `security-review`, `deploy_report`) and in `docs/10-architecture/01-agents.md` / `docs/50-features/03-knowledge-sync.md` (`technical_design`) was already present in that union.

Hyphen/underscore/synonym variants that appear as real, independent usage (for example both `test-plan` and `test_plan`, both `security-review` and `security_review`) are each listed as their own valid entry rather than one being silently coerced into the other — coercion was explicitly out of scope for this fix.

## Extending the set

Add a type only when there is real evidence of intentional use — a framework doc, an agent definition, or a genuine (non-probe) work product already stored somewhere. Do not add a type just because a single CLI invocation needs it; that is exactly the shortcut that caused the original defect. When adding, keep `WP_VALID_TYPES` sorted and update this document's provenance note if the justification isn't self-evident from the addition itself.

## What this does not gate

Validation only applies to new writes via `store_wp`. Reading, listing, and searching existing work products always work regardless of their stored `type` — including rows whose type predates this allowlist or was written directly to the database outside `tc`. Nothing here touches `get_wp`, `list_wps`, or `search_wps`.
