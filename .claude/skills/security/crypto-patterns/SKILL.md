---
name: crypto-patterns
description: >-
  Cryptographic patterns for encryption, hashing, key derivation functions
  (KDFs), TLS configuration, JWT signing, password storage, and authentication
  tokens — with deterministic weak-algorithm detection script. Identifies use of
  deprecated algorithms (MD5, SHA1, DES, ECB mode) and insecure configurations.
  Use proactively when reviewing code that uses encryption, hashing, or key
  management, auditing password storage or authentication tokens, checking TLS
  configuration, reviewing JWT signing algorithms, or any context where
  cryptographic primitives are chosen or configured. Run the validator for
  deterministic weak-algorithm detection.
version: 2.0.0
source: derived from .claude/skills/security/crypto-patterns.md (v1.0); L3 validator added 2026-05-20
when_to_use:
  - Reviewing code that uses encryption, hashing, or key management
  - Auditing password storage or authentication tokens
  - Checking TLS configuration
  - Reviewing JWT signing algorithms
  - Any context where cryptographic primitives are chosen or configured
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash
---

# Cryptographic Patterns

Secure cryptographic patterns and deterministic weak-algorithm detection. The prose guidance covers intent and context; the script provides consistent, reference-backed PASS/WARN/FAIL verdicts.

Cryptographic **guidance** (when to use what) is prose judgment — the model reasons about context, threat model, and trade-offs. Weak-algorithm **detection** is deterministic — the script checks algorithm names, key sizes, modes, and work factors against published standards (NIST SP 800-131A, OWASP, Mozilla TLS, RFC 8725).

Never approve a cryptographic configuration without running the validator.

## Invocation — Crypto Configuration Validator (L3 Script)

Assemble the cryptographic usages as a JSON array and run the validator. Consume its **output only** — the script source never enters context.

**Format each usage:**
```json
[
  {
    "name": "user password storage",
    "type": "kdf",
    "algorithm": "bcrypt",
    "work_factor": 12
  },
  {
    "name": "API payload encryption",
    "type": "symmetric",
    "algorithm": "aes-256",
    "key_bits": 256,
    "mode": "GCM"
  },
  {
    "name": "auth token signing",
    "type": "jwt",
    "algorithm": "RS256",
    "jwt_alg": "RS256"
  }
]
```

**Required fields per entry:**
- `name` — human-readable label (e.g. "user session token")
- `type` — usage type: `symmetric` | `hash` | `kdf` | `asymmetric` | `prng` | `tls` | `jwt`
- `algorithm` — algorithm/cipher name (case-insensitive)

**Optional fields (add any that apply):**
- `key_bits` — key length in bits (symmetric and asymmetric)
- `mode` — cipher mode (symmetric; e.g. `GCM`, `CBC`, `ECB`)
- `iv_reuse` — `true` if the IV/nonce is reused (always triggers FAIL)
- `work_factor` — cost parameter (KDFs; bcrypt cost, argon2 iterations, etc.)
- `tls_version` — TLS/SSL version string (type=tls; e.g. `"TLS1.2"`, `"1.3"`)
- `jwt_alg` — JWT algorithm header value (type=jwt; e.g. `"RS256"`, `"none"`)

**Run via Bash (file argument):**
```bash
python .claude/skills/security/crypto-patterns/scripts/crypto_check.py config.json
```

**Run via Bash (stdin):**
```bash
echo '<json array>' | python .claude/skills/security/crypto-patterns/scripts/crypto_check.py -
```

**The script outputs:**
1. A JSON object with `findings` (each entry with `result` and `rationale`) and a `summary` of PASS/WARN/FAIL counts.
2. A markdown audit table sorted by severity (FAIL first, then WARN, then PASS).
3. An explicit FAIL list if any FAIL items are present.

**Result meanings:**
- `PASS` — algorithm/configuration meets current standards
- `WARN` — acceptable but non-ideal; review the rationale and consider upgrading
- `FAIL` — broken, deprecated, or dangerous; must be addressed

**Error handling:** Non-zero exit on malformed JSON, missing required fields, or unknown usage type. Fix and re-run.

**What the agent does with the output:**
1. All FAIL items must be remediated before approving the code.
2. WARN items should be evaluated — document acceptance rationale if keeping.
3. Reference the `rationale` strings in remediation notes (they cite the standard).

## Standards Reference

| Standard | What It Covers |
|----------|----------------|
| NIST SP 800-131A Rev 2 | Symmetric and asymmetric key size minimums |
| OWASP Password Storage CS | KDF algorithm and work factor minimums |
| Mozilla Server Side TLS | TLS version and cipher suite guidance |
| RFC 8725 | JWT Best Current Practices |

## Cryptographic Guidance

### Password Storage

**Correct hierarchy (most to least preferred):**
1. **Argon2id** — OWASP recommended; memory-hard, resistant to GPU brute-force
2. **bcrypt** — widely supported, proven; cost factor >= 10
3. **scrypt** — memory-hard; N >= 2^14
4. PBKDF2 — acceptable if iterations are high (>= 310,000 for HMAC-SHA256); weaker than above

**Never:** MD5, SHA-1, SHA-256, or any plain hash for passwords. Never store plaintext.

### Symmetric Encryption

**Prefer:** AES-256-GCM (authenticated encryption; random 96-bit IV per operation)

**Acceptable:** ChaCha20-Poly1305 (modern AEAD; preferred on mobile/embedded)

**Avoid:**
- ECB mode (patterns visible in ciphertext)
- CBC without HMAC (unauthenticated; ciphertext malleable)
- Any reused IV/nonce (catastrophic for stream ciphers and GCM)
- Key sizes below 128 bits

### Asymmetric Keys

- **RSA:** >= 2048 bits minimum; 3072+ preferred for new systems
- **ECDSA/ECDH:** P-256 (256-bit) or stronger; never < 224 bits
- **Modern preference:** Ed25519 / X25519 (fixed-size, fast, safe by design)

### JWT Signing

- **Preferred:** PS256/PS384/PS512 (RSA-PSS, per RFC 8725) or ES256/ES384
- **Acceptable:** RS256/RS384/RS512
- **Caution:** HS256/HS384/HS512 — symmetric; only safe when the secret is never shared externally
- **Never:** `alg: none` — disables verification entirely

### TLS

- **Minimum:** TLS 1.2 (Mozilla intermediate profile)
- **Preferred:** TLS 1.3 (Mozilla modern profile)
- **Prohibited:** SSLv2, SSLv3, TLS 1.0, TLS 1.1 (all deprecated by RFC 8996)

### PRNG

- Always use a CSPRNG: `crypto.randomBytes()` (Node.js), `os.urandom()` / `secrets` (Python), `crypto/rand` (Go), `SecureRandom` (Java)
- Never use `Math.random()` or language-level `rand()` for any security purpose

## Anti-Generic Rules

- NEVER approve a crypto configuration without running the validator script
- NEVER manually compute whether a key size is "probably fine" — the script cites the standard
- NEVER use ECB mode under any circumstances
- NEVER accept IV/nonce reuse — regenerate randomly every time
- NEVER use MD5 or SHA-1 for any security-relevant hash
- NEVER store passwords with a plain hash (SHA-256 included)
- NEVER use `alg: none` in JWT — it is not a test convenience, it is a vulnerability

**Self-Critique:** "Did I run the validator and address every FAIL? Did I document acceptance rationale for any WARN items I chose to keep? Are there any crypto usages in this codebase I haven't listed in the input?"
