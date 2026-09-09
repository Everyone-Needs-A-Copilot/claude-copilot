# ADR-001: Finish a bounded delivery, then stop

Status: Accepted for this batch by the owner's explicit stopping-point request.

The recurring failure mode is a moving finish line: one finding creates another
audit, test expansion or unrelated improvement. The user cannot tell when the work
will end, while a green process still does not establish the intended behavior.

Freeze observable acceptance, consumers, exclusions and verification caps before
implementation. Use the existing source-bound `tc` gate, not a new approval
engine. Fix caused failures using affected checks; unrelated findings do not
silently extend the batch. A pre-existing failure that prevents acceptance remains
a blocker. Neither a time cap nor a desire to finish can turn missing evidence
into approval.

Once all required criteria have current QA approval, close the batch, report the
completed scope and separately pending work, and stop. Another improvement cycle
requires a new request. The native instructions express this workflow; they are
not a scheduler, a model-compliance guarantee or permission to bypass hooks.

Keep the existing setup authority. "One starting point" means a short, clear path
through supported setup, not another partial installer. Optional design feedback,
specialist packs, cloud execution and private learning stay explicit choices.

Keep visibility read-only and local. Reuse observed verification artifacts and
foundation declarations; do not probe credentials to fill a dashboard. Missing
agent/context/token observations are unknown. Parallel task wall times cannot be
summed into elapsed session time, and API estimates are not subscription bills.
