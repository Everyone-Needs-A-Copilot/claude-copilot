# Concurrent budget lock correction in 5.34.1

## Measured failure

The unchanged `test_same_session_concurrent_calls_all_record_their_targets` invokes four real Bash hooks with one session and four distinct file targets. The accepted 5.34.0 PR passed; main and later bounded diagnostic samples intermittently retained only two or three targets. All four processes returned zero with empty stderr. Local unchanged tests and controlled contention passed; selecting the officially verified jq1.8.1 binary alone also passed on the local host. These results did not establish a Bash or jq cause.

The decisive CI trace is [job126869458419](https://github.com/Everyone-Needs-A-Copilot/claude-copilot/actions/runs/41914211364/job/126869458419), source `efe19cc8a528cb0238cd6537730b98f625848a25`. It measured GNU Bash5.3.9, jq1.8.1 and Python3.12.16 on Linux. At epoch1793826890.871669 and .871684, callers2547 and2549 both passed the same external-mkdir lock admission and selected `/dev/null` as prior state. Neither reached release until .880327 or later. Each wrote a one-target state, proving overlapping admission and lost updates; no inherited EXIT release or diagnosed error path preceded admission. The exact external utility identity and independent direct-utility control are recorded by the corrected CI runner rather than guessed.

Full original logs and parsed per-caller traces remain local in the publisher CSE evidence directory `.copilot/orchestration-release-20261104/`. Earlier truncated diagnostic attempts and their corrections are retained. One diagnostic command addition violated the existing exact-command CI test; it was corrected through `PYTEST_ADDOPTS`, preserving that test and the canonical command.

## Correction and validation contract

Use atomic shell noclobber file creation instead of accepting external `mkdir` success as exclusive ownership. Bind release to the creator process/subshell, a held flag, the unchanged token and a regular non-symlink file. Existing directory locks and unknown owners remain held; mixed old/new processes must wait. Keep the same bounded waiting, thresholds, denied-target behavior and QA/journey gates.

The original21 budget tests and hook shell checks remain unchanged. CI runs ten bounded instances of the existing concurrent case and fails immediately on any failure, then runs the complete root suite. The full tc, cc, conformance, onboarding, smoke, static evaluation, CodeQL and remaining automatic checks stay required for the exact candidate and resulting main. The local role lifecycle smoke still spends zero model tokens; it is not a native model-quality or productivity benchmark.

The 5.34.0 signed tag is retained as history. Consumer pins and installed activation advance only after verified signed 5.34.1 publication and successful current checks. Installed QA must bind the final source and runtime; earlier candidate or historical acceptance does not stand in for that verification.
