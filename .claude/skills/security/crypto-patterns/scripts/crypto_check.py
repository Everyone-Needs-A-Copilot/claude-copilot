#!/usr/bin/env python3
"""
Cryptographic Configuration Validator — L3 executable for the crypto-patterns skill.

Purpose:
  Given a structured description of cryptographic usage (algorithm, key size, mode, etc.),
  classify each usage as PASS, WARN, or FAIL with a deterministic rationale.
  Covers: symmetric ciphers, asymmetric/RSA/EC, hash functions, password KDFs, PRNG,
  TLS configuration, and JWT signing algorithms.

This is NOT a runtime scanner — it validates a configuration description you supply.
The judgment about which algorithms are insecure is derived from published standards
(NIST SP 800-131A, OWASP, Mozilla Server Side TLS). No voodoo constants.

Input (file path as first argument, or '-'/no-arg for stdin):
  JSON array of usage objects:
  [
    {
      "name": "user password storage",    // human label (required)
      "type": "kdf",                      // usage type (required; see TYPES below)
      "algorithm": "bcrypt",              // algorithm/cipher name (required)
      // type-specific optional fields:
      "key_bits": 128,                    // key length in bits (symmetric, asymmetric)
      "mode": "ECB",                      // cipher mode (symmetric)
      "iv_reuse": true,                   // explicit IV reuse flag (symmetric)
      "work_factor": 4,                   // bcrypt cost factor / argon2 iteration count
      "tls_version": "1.1",              // TLS/SSL version (tls type)
      "jwt_alg": "none"                  // JWT algorithm (jwt type)
    },
    ...
  ]

Usage types:
  symmetric    — AES, 3DES, DES, ChaCha20, RC4, Blowfish, ...
  hash         — SHA-256, SHA-1, MD5, SHA-3, BLAKE2, ...
  kdf          — bcrypt, argon2, scrypt, PBKDF2, MD5 (as KDF), ...
  asymmetric   — RSA, EC/ECDSA/ECDH, DSA, ...
  prng         — Math.random, crypto.randomBytes, SecureRandom, ...
  tls          — TLS/SSL configuration entry
  jwt          — JWT signing algorithm

Output (stdout):
  1. JSON object: { findings (each with result/rationale), summary }
  2. Markdown: validation table with PASS/WARN/FAIL for each entry

Exit codes:
  0 — success (even if all FAIL — the caller decides what to block on)
  1 — invalid input (bad JSON, missing required field, unknown type)

Rationale references:
  - NIST SP 800-131A Rev 2 (symmetric/asymmetric key sizes)
  - OWASP Password Storage Cheat Sheet (KDF work factors)
  - Mozilla Server Side TLS (https://wiki.mozilla.org/Security/Server_Side_TLS)
  - RFC 8725 (JWT Best Current Practices)
"""

import argparse
import json
import sys

# ---------------------------------------------------------------------------
# Result constants
# ---------------------------------------------------------------------------
PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

# ---------------------------------------------------------------------------
# Usage type catalog
# ---------------------------------------------------------------------------
USAGE_TYPES = ("symmetric", "hash", "kdf", "asymmetric", "prng", "tls", "jwt")

# ---------------------------------------------------------------------------
# Symmetric cipher rules
# Reference: NIST SP 800-131A Rev 2
# ---------------------------------------------------------------------------

# Algorithms: FAIL (broken), WARN (legacy), PASS (modern)
SYMMETRIC_ALG_RESULTS: dict[str, tuple[str, str]] = {
    # Broken — FAIL
    "des":          (FAIL, "DES has 56-bit effective key size; broken since 1998 (NIST deprecated 2004)."),
    "3des":         (FAIL, "Triple-DES deprecated by NIST SP 800-131A Rev 2 (2019); vulnerable to Sweet32."),
    "tdea":         (FAIL, "TDEA (=3DES) deprecated by NIST SP 800-131A Rev 2 (2019)."),
    "rc4":          (FAIL, "RC4 is cryptographically broken; prohibited by RFC 7465."),
    "rc2":          (FAIL, "RC2 is obsolete and broken."),
    "blowfish":     (WARN, "Blowfish has 64-bit block size (vulnerable to SWEET32 at high volumes); migrate to AES."),
    # Modern — PASS
    "aes":          (PASS, "AES is the NIST-approved symmetric cipher. Verify key size and mode separately."),
    "aes-128":      (PASS, "AES-128 is NIST-approved (128 bits meets security level 1)."),
    "aes-192":      (PASS, "AES-192 is NIST-approved."),
    "aes-256":      (PASS, "AES-256 is NIST-approved. Preferred for high-security contexts."),
    "chacha20":     (PASS, "ChaCha20 is a modern stream cipher; always pair with Poly1305 for authentication."),
    "chacha20-poly1305": (PASS, "ChaCha20-Poly1305 is a modern AEAD cipher."),
}

# Modes: FAIL (broken), WARN (unauthenticated), PASS (authenticated)
MODE_RESULTS: dict[str, tuple[str, str]] = {
    "ecb":          (FAIL, "ECB mode leaks patterns; never use for data with repeating blocks."),
    "cbc":          (WARN, "CBC mode is unauthenticated; requires separate HMAC or use GCM instead."),
    "cfb":          (WARN, "CFB mode is unauthenticated; use GCM or pair with HMAC."),
    "ofb":          (WARN, "OFB mode is unauthenticated; use GCM or pair with HMAC."),
    "ctr":          (WARN, "CTR mode is unauthenticated; use GCM or pair with HMAC."),
    "gcm":          (PASS, "GCM mode provides authenticated encryption (AEAD)."),
    "ccm":          (PASS, "CCM mode provides authenticated encryption (AEAD)."),
    "siv":          (PASS, "SIV mode provides nonce-misuse-resistant AEAD."),
    "poly1305":     (PASS, "Poly1305 provides authentication (used with ChaCha20)."),
}

# ---------------------------------------------------------------------------
# Hash function rules
# Reference: NIST SP 800-131A Rev 2
# ---------------------------------------------------------------------------
HASH_RESULTS: dict[str, tuple[str, str]] = {
    "md5":          (FAIL, "MD5 is cryptographically broken (collision attacks practical since 2005)."),
    "md4":          (FAIL, "MD4 is broken."),
    "sha1":         (FAIL, "SHA-1 deprecated by NIST (SHAttered collision attack 2017)."),
    "sha-1":        (FAIL, "SHA-1 deprecated by NIST (SHAttered collision attack 2017)."),
    "sha256":       (PASS, "SHA-256 is NIST-approved and recommended."),
    "sha-256":      (PASS, "SHA-256 is NIST-approved and recommended."),
    "sha384":       (PASS, "SHA-384 is NIST-approved."),
    "sha-384":      (PASS, "SHA-384 is NIST-approved."),
    "sha512":       (PASS, "SHA-512 is NIST-approved."),
    "sha-512":      (PASS, "SHA-512 is NIST-approved."),
    "sha3-256":     (PASS, "SHA3-256 is NIST-approved."),
    "sha3-512":     (PASS, "SHA3-512 is NIST-approved."),
    "blake2b":      (PASS, "BLAKE2b is a modern, fast hash function."),
    "blake2s":      (PASS, "BLAKE2s is a modern, fast hash function."),
    "blake3":       (PASS, "BLAKE3 is a modern hash function."),
    "ripemd-160":   (WARN, "RIPEMD-160 is not NIST-approved; prefer SHA-256 for new designs."),
    "crc32":        (FAIL, "CRC32 is a checksum, NOT a cryptographic hash; do not use for security purposes."),
}

# ---------------------------------------------------------------------------
# KDF (Key Derivation Function / password hashing) rules
# Reference: OWASP Password Storage Cheat Sheet
# ---------------------------------------------------------------------------
# Minimum work factors to avoid WARN:
KDF_MIN_WORK_FACTOR: dict[str, int] = {
    "bcrypt": 10,          # cost parameter; OWASP recommends >= 10
    "argon2": 3,           # iterations (memory factor also matters but not captured here)
    "argon2id": 3,
    "argon2i": 3,
    "argon2d": 3,
    "scrypt": 14,          # N as log2 (2^14 = 16384 minimum)
    "pbkdf2": 310000,      # OWASP 2023 recommendation for PBKDF2-HMAC-SHA256
}

KDF_ALG_RESULTS: dict[str, tuple[str, str]] = {
    # Good KDFs
    "argon2id":     (PASS, "Argon2id is the OWASP-recommended password hashing algorithm."),
    "argon2i":      (PASS, "Argon2i is suitable for password hashing (prefer Argon2id)."),
    "argon2d":      (WARN, "Argon2d is vulnerable to side-channel attacks in some contexts; prefer Argon2id."),
    "argon2":       (PASS, "Argon2 (unspecified variant); prefer Argon2id explicitly."),
    "bcrypt":       (PASS, "bcrypt is a proven, widely-supported password hash. Check work factor >= 10."),
    "scrypt":       (PASS, "scrypt is a memory-hard KDF; check N >= 2^14."),
    "pbkdf2":       (WARN, "PBKDF2 is acceptable but weaker than Argon2id/bcrypt; ensure high iteration count."),
    # Broken as KDFs
    "md5":          (FAIL, "MD5 is broken and must never be used as a KDF or password hash."),
    "sha1":         (FAIL, "SHA-1 is broken; never use as a password hash."),
    "sha256":       (FAIL, "SHA-256 without memory/time hardening is not a KDF; use bcrypt or Argon2id."),
    "sha512":       (FAIL, "SHA-512 without memory/time hardening is not a KDF; use bcrypt or Argon2id."),
    "plain":        (FAIL, "Plain text password storage is catastrophic."),
    "plaintext":    (FAIL, "Plain text password storage is catastrophic."),
    "none":         (FAIL, "No KDF specified for password storage is catastrophic."),
}

# ---------------------------------------------------------------------------
# Asymmetric key rules
# Reference: NIST SP 800-131A Rev 2 — Table 2
# RSA/DSA: >= 2048 bits (112-bit security); >= 3072 for 128-bit security.
# EC: >= 224 bits (112-bit security); >= 256 for 128-bit security.
# ---------------------------------------------------------------------------
ASYMMETRIC_ALG_RESULTS: dict[str, tuple[str, str]] = {
    "rsa":          (PASS, "RSA is acceptable; check key_bits >= 2048 (prefer 3072+)."),
    "dsa":          (WARN, "DSA (classic) is largely superseded; prefer ECDSA or RSA. Check key_bits >= 2048."),
    "dh":           (WARN, "Classic DH key exchange; prefer ECDH. Check group >= 2048 bits."),
    "ecdsa":        (PASS, "ECDSA is approved; check curve/key_bits >= 224 (prefer P-256 / 256-bit)."),
    "ecdh":         (PASS, "ECDH is approved for key agreement; check curve/key_bits >= 224."),
    "ed25519":      (PASS, "Ed25519 uses a 256-bit key on Curve25519; modern and recommended."),
    "ed448":        (PASS, "Ed448 provides higher security margin."),
    "x25519":       (PASS, "X25519 (ECDH on Curve25519) is modern and recommended."),
    "x448":         (PASS, "X448 provides higher security margin."),
    "elgamal":      (WARN, "ElGamal is non-standard for modern use; prefer RSA or EC."),
}
# Minimum key sizes for asymmetric algorithms
ASYMMETRIC_MIN_KEY_BITS: dict[str, tuple[int, str]] = {
    "rsa": (2048, "RSA key must be >= 2048 bits (NIST SP 800-131A). Prefer 3072+."),
    "dsa": (2048, "DSA key must be >= 2048 bits."),
    "dh":  (2048, "DH group must be >= 2048 bits."),
}
ASYMMETRIC_WEAK_EC_BITS = 224  # anything < this is FAIL for EC

# ---------------------------------------------------------------------------
# Symmetric key size minimums
# Reference: NIST SP 800-131A — 112-bit security = 128-bit key for AES
# ---------------------------------------------------------------------------
SYMMETRIC_MIN_KEY_BITS = 128  # below this -> FAIL for symmetric

# ---------------------------------------------------------------------------
# PRNG rules
# ---------------------------------------------------------------------------
PRNG_RESULTS: dict[str, tuple[str, str]] = {
    "math.random":      (FAIL, "Math.random() is NOT cryptographically secure; use crypto.randomBytes()."),
    "random":           (WARN, "Unspecified 'random'; verify this is a CSPRNG (e.g. crypto.randomBytes)."),
    "rand":             (WARN, "Unspecified 'rand'; verify this is a CSPRNG."),
    "crypto.randombytes": (PASS, "crypto.randomBytes() is a CSPRNG."),
    "crypto.randombytes()": (PASS, "crypto.randomBytes() is a CSPRNG."),
    "securerandom":     (PASS, "SecureRandom (Java) is a CSPRNG."),
    "os.urandom":       (PASS, "os.urandom() is a CSPRNG backed by the OS."),
    "secrets":          (PASS, "Python secrets module uses os.urandom(); CSPRNG."),
    "crypto/rand":      (PASS, "Go crypto/rand is a CSPRNG."),
    "openssl_random_pseudo_bytes": (PASS, "openssl_random_pseudo_bytes is a CSPRNG."),
    "random_bytes":     (PASS, "PHP random_bytes() is a CSPRNG."),
}

# ---------------------------------------------------------------------------
# TLS version rules
# Reference: Mozilla Server Side TLS (modern profile)
# ---------------------------------------------------------------------------
TLS_VERSION_RESULTS: dict[str, tuple[str, str]] = {
    "ssl2":     (FAIL, "SSLv2 is broken; deprecated by RFC 6176."),
    "ssl3":     (FAIL, "SSLv3 is broken (POODLE); deprecated by RFC 7568."),
    "sslv2":    (FAIL, "SSLv2 is broken."),
    "sslv3":    (FAIL, "SSLv3 is broken."),
    "tls1":     (FAIL, "TLS 1.0 is deprecated by RFC 8996 (2021)."),
    "tls1.0":   (FAIL, "TLS 1.0 is deprecated by RFC 8996 (2021)."),
    "tls 1.0":  (FAIL, "TLS 1.0 is deprecated by RFC 8996 (2021)."),
    "tls1.1":   (FAIL, "TLS 1.1 is deprecated by RFC 8996 (2021)."),
    "tls 1.1":  (FAIL, "TLS 1.1 is deprecated by RFC 8996 (2021)."),
    "1.0":      (FAIL, "TLS 1.0 is deprecated."),
    "1.1":      (FAIL, "TLS 1.1 is deprecated."),
    "tls1.2":   (PASS, "TLS 1.2 is acceptable (Mozilla intermediate profile)."),
    "tls 1.2":  (PASS, "TLS 1.2 is acceptable."),
    "1.2":      (PASS, "TLS 1.2 is acceptable."),
    "tls1.3":   (PASS, "TLS 1.3 is the current recommended version (Mozilla modern profile)."),
    "tls 1.3":  (PASS, "TLS 1.3 is recommended."),
    "1.3":      (PASS, "TLS 1.3 is recommended."),
    "tlsv1.2":  (PASS, "TLS 1.2 is acceptable."),
    "tlsv1.3":  (PASS, "TLS 1.3 is recommended."),
}

# ---------------------------------------------------------------------------
# JWT algorithm rules
# Reference: RFC 8725 — JWT Best Current Practices
# ---------------------------------------------------------------------------
JWT_ALG_RESULTS: dict[str, tuple[str, str]] = {
    "none":     (FAIL, "JWT 'none' algorithm disables signature verification; prohibited by RFC 8725."),
    "hs256":    (WARN, "HS256 is symmetric; safe only if the secret is shared securely between all verifiers."),
    "hs384":    (WARN, "HS384 is symmetric; same caveat as HS256."),
    "hs512":    (WARN, "HS512 is symmetric; same caveat as HS256."),
    "rs256":    (PASS, "RS256 (RSA + SHA-256) is widely supported and safe."),
    "rs384":    (PASS, "RS384 is safe."),
    "rs512":    (PASS, "RS512 is safe."),
    "ps256":    (PASS, "PS256 (RSA-PSS) is preferred over RS256 by RFC 8725."),
    "ps384":    (PASS, "PS384 is preferred."),
    "ps512":    (PASS, "PS512 is preferred."),
    "es256":    (PASS, "ES256 (ECDSA P-256) is recommended for compact tokens."),
    "es384":    (PASS, "ES384 is safe."),
    "es512":    (PASS, "ES512 is safe."),
    "eddsa":    (PASS, "EdDSA (Ed25519/Ed448) is modern and recommended."),
}


# ---------------------------------------------------------------------------
# Validation logic
# ---------------------------------------------------------------------------

def validate_usage(usage: object, index: int) -> dict:
    """Validate one usage dict. Returns cleaned dict with required fields, or raises ValueError."""
    if not isinstance(usage, dict):
        raise ValueError(f"Entry at index {index} must be a JSON object, got {type(usage).__name__}")

    if "name" not in usage:
        raise ValueError(f"Entry at index {index} missing required field 'name'")
    name = usage["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"Entry at index {index}: 'name' must be a non-empty string")

    if "type" not in usage:
        raise ValueError(
            f"Entry '{name}' (index {index}) missing required field 'type'. "
            f"Valid types: {', '.join(USAGE_TYPES)}."
        )
    usage_type = usage["type"]
    if not isinstance(usage_type, str) or usage_type.strip().lower() not in USAGE_TYPES:
        raise ValueError(
            f"Entry '{name}' (index {index}): unknown type '{usage_type}'. "
            f"Valid types: {', '.join(USAGE_TYPES)}."
        )

    if "algorithm" not in usage:
        raise ValueError(
            f"Entry '{name}' (index {index}) missing required field 'algorithm'."
        )
    algorithm = usage["algorithm"]
    if not isinstance(algorithm, str) or not algorithm.strip():
        raise ValueError(f"Entry '{name}' (index {index}): 'algorithm' must be a non-empty string")

    return {
        "name": name.strip(),
        "type": usage_type.strip().lower(),
        "algorithm": algorithm.strip(),
        **{k: usage[k] for k in ("key_bits", "mode", "iv_reuse", "work_factor", "tls_version", "jwt_alg") if k in usage},
    }


def check_usage(usage: dict) -> dict:
    """
    Run deterministic checks for one usage entry.
    Returns the entry augmented with 'result' (PASS/WARN/FAIL) and 'rationale' (list of strings).
    """
    name = usage["name"]
    utype = usage["type"]
    alg = usage["algorithm"].lower()
    rationale: list[str] = []
    results: list[str] = []

    if utype == "symmetric":
        alg_result, alg_msg = SYMMETRIC_ALG_RESULTS.get(alg, (WARN, f"Unknown symmetric algorithm '{usage['algorithm']}'; cannot verify safety."))
        results.append(alg_result)
        rationale.append(alg_msg)

        # Check key size
        if "key_bits" in usage:
            kb = usage["key_bits"]
            if not isinstance(kb, int) or isinstance(kb, bool):
                raise ValueError(f"Entry '{name}': 'key_bits' must be an integer.")
            if kb < SYMMETRIC_MIN_KEY_BITS:
                results.append(FAIL)
                rationale.append(f"key_bits={kb} is below minimum {SYMMETRIC_MIN_KEY_BITS} bits (NIST SP 800-131A).")
            else:
                results.append(PASS)
                rationale.append(f"key_bits={kb} meets the {SYMMETRIC_MIN_KEY_BITS}-bit minimum.")

        # Check mode
        if "mode" in usage:
            mode = usage["mode"].lower()
            mode_result, mode_msg = MODE_RESULTS.get(mode, (WARN, f"Unknown mode '{usage['mode']}'; verify it provides authentication."))
            results.append(mode_result)
            rationale.append(mode_msg)

        # IV reuse
        if usage.get("iv_reuse") is True:
            results.append(FAIL)
            rationale.append("IV/nonce reuse breaks confidentiality and (in GCM) authentication. Always generate a fresh random IV per encryption.")

    elif utype == "hash":
        hash_result, hash_msg = HASH_RESULTS.get(alg, (WARN, f"Unknown hash algorithm '{usage['algorithm']}'; verify it is NIST-approved."))
        results.append(hash_result)
        rationale.append(hash_msg)

    elif utype == "kdf":
        kdf_result, kdf_msg = KDF_ALG_RESULTS.get(alg, (WARN, f"Unknown KDF '{usage['algorithm']}'; verify it is a memory-hard password hashing function."))
        results.append(kdf_result)
        rationale.append(kdf_msg)

        # Work factor check
        if alg in KDF_MIN_WORK_FACTOR and "work_factor" in usage:
            wf = usage["work_factor"]
            if not isinstance(wf, (int, float)) or isinstance(wf, bool):
                raise ValueError(f"Entry '{name}': 'work_factor' must be a number.")
            min_wf = KDF_MIN_WORK_FACTOR[alg]
            if float(wf) < min_wf:
                results.append(WARN)
                rationale.append(
                    f"work_factor={wf} is below the recommended minimum of {min_wf} for {usage['algorithm']}."
                )
            else:
                results.append(PASS)
                rationale.append(f"work_factor={wf} meets the recommended minimum.")

    elif utype == "asymmetric":
        asym_result, asym_msg = ASYMMETRIC_ALG_RESULTS.get(alg, (WARN, f"Unknown asymmetric algorithm '{usage['algorithm']}'; verify it meets current standards."))
        results.append(asym_result)
        rationale.append(asym_msg)

        if "key_bits" in usage:
            kb = usage["key_bits"]
            if not isinstance(kb, int) or isinstance(kb, bool):
                raise ValueError(f"Entry '{name}': 'key_bits' must be an integer.")
            # RSA/DSA/DH have bit-length minimums
            if alg in ASYMMETRIC_MIN_KEY_BITS:
                min_kb, min_msg = ASYMMETRIC_MIN_KEY_BITS[alg]
                if kb < min_kb:
                    results.append(FAIL)
                    rationale.append(f"key_bits={kb}: {min_msg}")
                else:
                    results.append(PASS)
                    rationale.append(f"key_bits={kb} meets the {min_kb}-bit minimum for {usage['algorithm'].upper()}.")
            # EC algorithms
            elif alg in ("ecdsa", "ecdh"):
                if kb < ASYMMETRIC_WEAK_EC_BITS:
                    results.append(FAIL)
                    rationale.append(f"key_bits={kb} is below 224 bits; EC keys must be >= 224 bits (NIST).")
                else:
                    results.append(PASS)
                    rationale.append(f"key_bits={kb} meets the {ASYMMETRIC_WEAK_EC_BITS}-bit EC minimum.")

    elif utype == "prng":
        prng_result, prng_msg = PRNG_RESULTS.get(alg, (WARN, f"Unknown PRNG '{usage['algorithm']}'; verify it is a CSPRNG backed by the OS."))
        results.append(prng_result)
        rationale.append(prng_msg)

    elif utype == "tls":
        # Check tls_version field (preferred) or fall back to algorithm field
        tls_ver = usage.get("tls_version", usage["algorithm"]).strip().lower()
        tls_result, tls_msg = TLS_VERSION_RESULTS.get(tls_ver, (WARN, f"Unknown TLS version '{usage.get('tls_version', usage['algorithm'])}'; verify >= TLS 1.2."))
        results.append(tls_result)
        rationale.append(tls_msg)

    elif utype == "jwt":
        # Check jwt_alg field (preferred) or fall back to algorithm field
        jwt_alg = usage.get("jwt_alg", usage["algorithm"]).strip().lower()
        jwt_result, jwt_msg = JWT_ALG_RESULTS.get(jwt_alg, (WARN, f"Unknown JWT algorithm '{usage.get('jwt_alg', usage['algorithm'])}'; verify against RFC 8725."))
        results.append(jwt_result)
        rationale.append(jwt_msg)

    # Aggregate result: FAIL > WARN > PASS
    if FAIL in results:
        final = FAIL
    elif WARN in results:
        final = WARN
    else:
        final = PASS

    return {**usage, "result": final, "rationale": rationale}


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_input(source: str | None) -> list:
    if source is None or source == "-":
        raw = sys.stdin.read()
        label = "<stdin>"
    else:
        try:
            with open(source, encoding="utf-8") as fh:
                raw = fh.read()
        except FileNotFoundError:
            raise ValueError(f"Input file not found: {source}")
        except OSError as exc:
            raise ValueError(f"Cannot read input file '{source}': {exc}")
        label = source

    raw = raw.strip()
    if not raw:
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON from {label}: {exc}")

    if not isinstance(data, list):
        raise ValueError(
            f"Input from {label} must be a JSON array of usage objects, got {type(data).__name__}"
        )
    return data


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
RESULT_SYMBOLS = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL"}


def render_table(findings: list[dict]) -> str:
    lines = [
        "## Cryptographic Configuration Audit\n",
        "| # | Name | Type | Algorithm | Result | Notes |",
        "|---|------|------|-----------|--------|-------|",
    ]
    for i, f in enumerate(findings, 1):
        result = f["result"]
        marker = f"**{result}**" if result in (WARN, FAIL) else result
        notes = "; ".join(f["rationale"][:2])  # first 2 rationale lines to keep table readable
        lines.append(
            f"| {i} | {f['name']} | {f['type']} | {f['algorithm']} | {marker} | {notes} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def run(source: str | None) -> int:
    try:
        raw_usages = load_input(source)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not raw_usages:
        output = {"findings": [], "summary": "No usage entries provided."}
        print(json.dumps(output, indent=2))
        print()
        print("_No usage entries provided._")
        return 0

    validated: list[dict] = []
    for i, item in enumerate(raw_usages):
        try:
            validated.append(validate_usage(item, i))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    findings: list[dict] = []
    for usage in validated:
        try:
            findings.append(check_usage(usage))
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    # Sort: FAIL first, then WARN, then PASS
    result_order = {FAIL: 0, WARN: 1, PASS: 2}
    sorted_findings = sorted(findings, key=lambda f: result_order.get(f["result"], 3))

    summary = {
        "total": len(sorted_findings),
        "fail": sum(1 for f in sorted_findings if f["result"] == FAIL),
        "warn": sum(1 for f in sorted_findings if f["result"] == WARN),
        "pass": sum(1 for f in sorted_findings if f["result"] == PASS),
    }

    output = {"findings": sorted_findings, "summary": summary}
    print(json.dumps(output, indent=2))
    print()
    print(render_table(sorted_findings))

    # Print FAIL items explicitly
    fails = [f for f in sorted_findings if f["result"] == FAIL]
    if fails:
        print("\n**FAIL items require immediate action:**")
        for f in fails:
            print(f"- **{f['name']}** ({f['type']}/{f['algorithm']}): {f['rationale'][0]}")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Cryptographic configuration validator. Reads JSON usage descriptions, "
            "classifies each as PASS/WARN/FAIL with rationale."
        ),
        epilog=(
            "Input format: JSON array of objects with fields: "
            "name (str), type (symmetric|hash|kdf|asymmetric|prng|tls|jwt), algorithm (str), "
            "plus optional: key_bits (int), mode (str), iv_reuse (bool), work_factor (num), "
            "tls_version (str), jwt_alg (str). "
            "References: NIST SP 800-131A, OWASP Password Storage CS, Mozilla TLS, RFC 8725."
        ),
    )
    parser.add_argument(
        "source",
        nargs="?",
        default=None,
        help="Path to JSON usage file, or '-' to read from stdin (default: stdin)",
    )
    args = parser.parse_args()
    sys.exit(run(args.source))


if __name__ == "__main__":
    main()
