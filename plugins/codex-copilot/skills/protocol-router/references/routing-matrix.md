# Routing Matrix

## Role responsibilities

| Role | Focus | Output |
|------|-------|--------|
| `ta` | architecture, trade-offs, task breakdown | plan, ADR-style reasoning, task shape |
| `me` | implementation | code changes |
| `qa` | validation and regressions | reproduction notes, tests, verification |
| `sec` | threats and controls | security review |
| `doc` | explanation and docs | concise documentation |
| `do` | infra and delivery | scripts, CI, deployment updates |
| `sd` | service blueprint | journey framing and system touchpoints |
| `uxd` | interaction design | flows, states, usability choices |
| `uids` | visual direction | hierarchy, tokens, layout language |
| `uid` | interface implementation | components and styling |
| `ind` | industrial design | essential function, material honesty, physical-digital fit |

## Request matrix

Each arrow is a stage boundary, and each hop may fan out to several same-role agents on disjoint partitions with one synthesis owner per stage (see the protocol `parallel-execution` reference); a single agent per hop needs a recorded indivisibility reason.


| Request | Primary route | Optional additions |
|---------|---------------|-------------------|
| fix failing tests | `qa -> me -> qa` | `ta` if architecture is implicated |
| add API endpoint | `ta -> me -> qa` | `sec`, `doc` |
| redesign onboarding | `sd -> uxd -> uids -> uid -> ta -> me -> qa` | `doc` for durable docs; in-product language stays with `uxd`/`uids` |
| design connected-product experience | `ind -> sd -> uxd -> uids -> uid -> ta -> me -> qa` | `sec`, `do` |
| update dashboard visuals | `uids -> uid -> qa` | `uxd` |
| write migration plan | `ta` | `do`, `sec` |
| ship deployment fix | `do -> me -> qa` | `ta`, `sec` |
