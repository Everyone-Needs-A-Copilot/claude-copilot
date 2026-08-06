# Vendored doctor --json corpus fixture

`healthy-clean-fleet.json` is a VENDORED COPY of
`copilot-control-tower/src-tauri/fixtures/corpus/healthy-clean-fleet.json`,
used by `tests/test_doctor_contract.py`'s field-set parity assertion (the
real `cc doctor --json` checker/top-level key set must match what Control
Tower's own fixture corpus expects). Same precedent as `tests/fixtures/schemas/`
(see that directory's per-file `$comment` headers): update this copy from
the source of truth in `copilot-control-tower`, not the reverse.
