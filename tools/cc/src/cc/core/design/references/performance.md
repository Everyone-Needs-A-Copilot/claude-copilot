# Measured interaction and rendering cost

Name the observed delay or instability and the user action it affects. Reproduce
it with the relevant device, data volume, network and cache state. Read the code
that owns the behavior and measure before choosing a cause or optimization.

Inspect expensive renders, layout shifts, asset loading, main-thread work and
interaction latency with tools available in the project's actual runtime. Use
existing profiling and build analysis rather than introducing another observer.
Distinguish a development-build result from a production-build measurement.

Prefer changes that preserve the design contract: stable media dimensions,
appropriately sized assets, localized state updates, deferred nonessential work
and simpler DOM/layout where measured. Do not remove accessible names, necessary
content, error handling or expected interaction to improve a score.

Compare the same action and environment before and after, and verify persisted
effects and visual fidelity. Record cache and data conditions, tool versions,
actual measurements and any tradeoff. A green build or smaller bundle does not
alone establish a faster user experience. Preserve baseline behavior when the
claimed improvement is absent or task correctness regresses.
