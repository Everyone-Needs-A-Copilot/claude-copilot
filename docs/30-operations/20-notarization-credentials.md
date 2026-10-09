# Apple notarization credentials

Read before publishing/notarization work on the publisher Mac.

- The publisher Mac's `ct-notary` profile is a standing credential. The release
  environment stores its profile name, not the Apple password.
- Without an explicit `--keychain`, Apple `notarytool` stores the profile in the
  macOS Data Protection Keychain. Do not use `security find-generic-password`
  against `login.keychain-db` as an existence test.
- Probe with
  `xcrun notarytool history --keychain-profile ct-notary --output-format json`.
  Retry transient `No Keychain password item found` failures. If a later probe
  succeeds, continue the release and do not ask the owner to recreate the
  credential.
- Release scripts must preflight before expensive builds and retry only local
  Keychain-lookup failures at notarization boundaries. Never bypass signing,
  notarization, source verification, or artifact verification.
