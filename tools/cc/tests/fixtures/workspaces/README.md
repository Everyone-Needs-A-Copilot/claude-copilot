# Workspace project-integration fixtures

This directory is the source fixture corpus for the additive `cc workspace`
schema `1.1` contract.

- `project-integration-cases.json` describes synthetic repository layouts for
  classifier implementation tests. Paths are repository-relative, fixture tags
  stand in for content, and no entry names a real project.
- `reports/` contains complete machine-report fixtures validated against
  `tests/fixtures/schemas/workspaces.schema.json`.
- `invalid-report-mutations.json` applies one deliberate contract violation to
  a valid report for each fail-closed negative case.

The capability counts are observations attached to individual synthetic
layouts. They are deliberately varied and must never become thresholds for a
classification. A classifier has to recognize a complete versioned contract or
report what is missing; it cannot infer readiness from the amount of material
present.
