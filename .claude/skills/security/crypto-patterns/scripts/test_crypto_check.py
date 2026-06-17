"""
Tests for crypto_check.py — bundled alongside the validator.

Run with:  python3 -m pytest .claude/skills/security/crypto-patterns/scripts/test_crypto_check.py -v
Or from within this directory: python3 -m pytest test_crypto_check.py -v
"""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Load module
# ---------------------------------------------------------------------------
SCRIPT = Path(__file__).parent / "crypto_check.py"

import importlib.util

spec = importlib.util.spec_from_file_location("crypto_check", SCRIPT)
crypto_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crypto_check)

PASS = crypto_check.PASS
WARN = crypto_check.WARN
FAIL = crypto_check.FAIL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_usage(**overrides):
    base = {"name": "test-usage", "type": "symmetric", "algorithm": "aes-256"}
    base.update(overrides)
    return base


def run_script(args=(), stdin_text=None):
    cmd = [sys.executable, str(SCRIPT)] + list(args)
    result = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True)
    return result.returncode, result.stdout, result.stderr


def parse_json_output(out: str) -> dict:
    return json.loads(out.split("\n\n")[0])


# ---------------------------------------------------------------------------
# validate_usage
# ---------------------------------------------------------------------------


class TestValidateUsage:
    def test_minimal_valid(self):
        u = crypto_check.validate_usage(make_usage(), 0)
        assert u["name"] == "test-usage"
        assert u["type"] == "symmetric"

    def test_missing_name_raises(self):
        with pytest.raises(ValueError, match="'name'"):
            crypto_check.validate_usage({"type": "hash", "algorithm": "sha256"}, 0)

    def test_missing_type_raises(self):
        with pytest.raises(ValueError, match="'type'"):
            crypto_check.validate_usage({"name": "x", "algorithm": "sha256"}, 0)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="unknown type"):
            crypto_check.validate_usage(make_usage(type="magic"), 0)

    def test_missing_algorithm_raises(self):
        with pytest.raises(ValueError, match="'algorithm'"):
            crypto_check.validate_usage({"name": "x", "type": "hash"}, 0)

    def test_type_normalized_to_lowercase(self):
        u = crypto_check.validate_usage(make_usage(type="HASH", algorithm="sha256"), 0)
        assert u["type"] == "hash"

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="must be a JSON object"):
            crypto_check.validate_usage("not a dict", 0)

    def test_key_bits_preserved(self):
        u = crypto_check.validate_usage(make_usage(key_bits=256), 0)
        assert u["key_bits"] == 256


# ---------------------------------------------------------------------------
# check_usage — symmetric
# ---------------------------------------------------------------------------


class TestCheckSymmetric:
    def test_aes256_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes-256"}
        )
        assert f["result"] == PASS

    def test_des_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "des"}
        )
        assert f["result"] == FAIL

    def test_rc4_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "rc4"}
        )
        assert f["result"] == FAIL

    def test_3des_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "3des"}
        )
        assert f["result"] == FAIL

    def test_blowfish_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "blowfish"}
        )
        assert f["result"] == WARN

    def test_short_key_fail(self):
        # AES-128 algorithm is PASS but 64-bit key is FAIL
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes", "key_bits": 64}
        )
        assert f["result"] == FAIL

    def test_adequate_key_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes", "key_bits": 256}
        )
        assert f["result"] == PASS

    def test_ecb_mode_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes", "mode": "ECB"}
        )
        assert f["result"] == FAIL

    def test_gcm_mode_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes-256", "mode": "GCM"}
        )
        assert f["result"] == PASS

    def test_cbc_mode_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes", "mode": "CBC"}
        )
        assert f["result"] == WARN  # PASS alg + WARN mode -> WARN overall

    def test_iv_reuse_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes-256", "iv_reuse": True}
        )
        assert f["result"] == FAIL

    def test_iv_no_reuse_no_extra_result(self):
        # iv_reuse=False should not add FAIL
        f = crypto_check.check_usage(
            {
                "name": "x",
                "type": "symmetric",
                "algorithm": "aes-256",
                "iv_reuse": False,
            }
        )
        assert f["result"] == PASS

    def test_key_bits_not_int_raises(self):
        with pytest.raises(ValueError, match="'key_bits' must be an integer"):
            crypto_check.check_usage(
                {
                    "name": "x",
                    "type": "symmetric",
                    "algorithm": "aes",
                    "key_bits": "256",
                }
            )


# ---------------------------------------------------------------------------
# check_usage — hash
# ---------------------------------------------------------------------------


class TestCheckHash:
    def test_sha256_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "sha256"}
        )
        assert f["result"] == PASS

    def test_sha_256_hyphen_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "sha-256"}
        )
        assert f["result"] == PASS

    def test_md5_fail(self):
        f = crypto_check.check_usage({"name": "x", "type": "hash", "algorithm": "md5"})
        assert f["result"] == FAIL

    def test_sha1_fail(self):
        f = crypto_check.check_usage({"name": "x", "type": "hash", "algorithm": "sha1"})
        assert f["result"] == FAIL

    def test_crc32_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "crc32"}
        )
        assert f["result"] == FAIL

    def test_sha3_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "sha3-256"}
        )
        assert f["result"] == PASS

    def test_blake2b_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "blake2b"}
        )
        assert f["result"] == PASS

    def test_ripemd160_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "ripemd-160"}
        )
        assert f["result"] == WARN

    def test_unknown_hash_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "hash", "algorithm": "sha999"}
        )
        assert f["result"] == WARN


# ---------------------------------------------------------------------------
# check_usage — kdf
# ---------------------------------------------------------------------------


class TestCheckKdf:
    def test_argon2id_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "argon2id"}
        )
        assert f["result"] == PASS

    def test_bcrypt_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "bcrypt"}
        )
        assert f["result"] == PASS

    def test_bcrypt_low_work_factor_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "bcrypt", "work_factor": 4}
        )
        assert f["result"] == WARN

    def test_bcrypt_adequate_work_factor_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "bcrypt", "work_factor": 12}
        )
        assert f["result"] == PASS

    def test_md5_as_kdf_fail(self):
        f = crypto_check.check_usage({"name": "x", "type": "kdf", "algorithm": "md5"})
        assert f["result"] == FAIL

    def test_sha256_as_kdf_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "sha256"}
        )
        assert f["result"] == FAIL

    def test_plain_fail(self):
        f = crypto_check.check_usage({"name": "x", "type": "kdf", "algorithm": "plain"})
        assert f["result"] == FAIL

    def test_pbkdf2_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "kdf", "algorithm": "pbkdf2"}
        )
        assert f["result"] == WARN

    def test_work_factor_not_number_raises(self):
        with pytest.raises(ValueError, match="'work_factor' must be a number"):
            crypto_check.check_usage(
                {
                    "name": "x",
                    "type": "kdf",
                    "algorithm": "bcrypt",
                    "work_factor": "high",
                }
            )


# ---------------------------------------------------------------------------
# check_usage — asymmetric
# ---------------------------------------------------------------------------


class TestCheckAsymmetric:
    def test_rsa_2048_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "rsa", "key_bits": 2048}
        )
        assert f["result"] == PASS

    def test_rsa_1024_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "rsa", "key_bits": 1024}
        )
        assert f["result"] == FAIL

    def test_ecdsa_256_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "ecdsa", "key_bits": 256}
        )
        assert f["result"] == PASS

    def test_ecdsa_160_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "ecdsa", "key_bits": 160}
        )
        assert f["result"] == FAIL

    def test_ed25519_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "ed25519"}
        )
        assert f["result"] == PASS

    def test_dsa_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "asymmetric", "algorithm": "dsa"}
        )
        assert f["result"] == WARN

    def test_key_bits_not_int_raises(self):
        with pytest.raises(ValueError, match="'key_bits' must be an integer"):
            crypto_check.check_usage(
                {
                    "name": "x",
                    "type": "asymmetric",
                    "algorithm": "rsa",
                    "key_bits": "2048",
                }
            )


# ---------------------------------------------------------------------------
# check_usage — prng
# ---------------------------------------------------------------------------


class TestCheckPrng:
    def test_math_random_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "Math.random"}
        )
        assert f["result"] == FAIL

    def test_crypto_randombytes_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "crypto.randomBytes"}
        )
        assert f["result"] == PASS

    def test_os_urandom_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "os.urandom"}
        )
        assert f["result"] == PASS

    def test_securerandom_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "SecureRandom"}
        )
        assert f["result"] == PASS

    def test_secrets_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "secrets"}
        )
        assert f["result"] == PASS

    def test_unknown_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "prng", "algorithm": "rand_custom"}
        )
        assert f["result"] == WARN


# ---------------------------------------------------------------------------
# check_usage — tls
# ---------------------------------------------------------------------------


class TestCheckTls:
    def test_tls13_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "tls", "algorithm": "TLS1.3", "tls_version": "TLS1.3"}
        )
        assert f["result"] == PASS

    def test_tls12_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "tls", "algorithm": "TLS1.2", "tls_version": "TLS1.2"}
        )
        assert f["result"] == PASS

    def test_tls11_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "tls", "algorithm": "TLS", "tls_version": "TLS1.1"}
        )
        assert f["result"] == FAIL

    def test_tls10_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "tls", "algorithm": "TLS", "tls_version": "TLS1.0"}
        )
        assert f["result"] == FAIL

    def test_ssl3_fail(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "tls", "algorithm": "TLS", "tls_version": "SSL3"}
        )
        assert f["result"] == FAIL

    def test_algorithm_fallback(self):
        # Without tls_version field, uses algorithm
        f = crypto_check.check_usage({"name": "x", "type": "tls", "algorithm": "1.2"})
        assert f["result"] == PASS


# ---------------------------------------------------------------------------
# check_usage — jwt
# ---------------------------------------------------------------------------


class TestCheckJwt:
    def test_none_alg_fail(self):
        f = crypto_check.check_usage({"name": "x", "type": "jwt", "algorithm": "none"})
        assert f["result"] == FAIL

    def test_rs256_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "jwt", "algorithm": "RS256", "jwt_alg": "RS256"}
        )
        assert f["result"] == PASS

    def test_es256_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "jwt", "algorithm": "ES256", "jwt_alg": "ES256"}
        )
        assert f["result"] == PASS

    def test_hs256_warn(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "jwt", "algorithm": "HS256", "jwt_alg": "HS256"}
        )
        assert f["result"] == WARN

    def test_eddsa_pass(self):
        f = crypto_check.check_usage(
            {"name": "x", "type": "jwt", "algorithm": "EdDSA", "jwt_alg": "EdDSA"}
        )
        assert f["result"] == PASS

    def test_jwt_alg_fallback_to_algorithm(self):
        # Without jwt_alg field, falls back to algorithm
        f = crypto_check.check_usage({"name": "x", "type": "jwt", "algorithm": "none"})
        assert f["result"] == FAIL


# ---------------------------------------------------------------------------
# Aggregate result — FAIL wins over WARN wins over PASS
# ---------------------------------------------------------------------------


class TestAggregateResult:
    def test_fail_overrides_pass_in_same_entry(self):
        # AES-256 (PASS) + ECB mode (FAIL) = FAIL overall
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes-256", "mode": "ECB"}
        )
        assert f["result"] == FAIL

    def test_warn_overrides_pass(self):
        # AES-256 (PASS) + CBC mode (WARN) = WARN overall
        f = crypto_check.check_usage(
            {"name": "x", "type": "symmetric", "algorithm": "aes-256", "mode": "CBC"}
        )
        assert f["result"] == WARN


# ---------------------------------------------------------------------------
# load_input
# ---------------------------------------------------------------------------


class TestLoadInput:
    def test_empty_stdin(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO(""))
        assert crypto_check.load_input(None) == []

    def test_file_path(self, tmp_path):
        data = [make_usage()]
        p = tmp_path / "crypto.json"
        p.write_text(json.dumps(data))
        result = crypto_check.load_input(str(p))
        assert len(result) == 1

    def test_missing_file_raises(self):
        with pytest.raises(ValueError, match="not found"):
            crypto_check.load_input("/no/such/file.json")

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("{bad json"))
        with pytest.raises(ValueError, match="Invalid JSON"):
            crypto_check.load_input(None)

    def test_non_array_raises(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO('{"name":"x"}'))
        with pytest.raises(ValueError, match="must be a JSON array"):
            crypto_check.load_input(None)


# ---------------------------------------------------------------------------
# Subprocess integration
# ---------------------------------------------------------------------------


class TestSubprocessIntegration:
    def test_valid_input_exits_zero(self):
        usages = [make_usage()]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0

    def test_fail_item_in_output(self):
        usages = [make_usage(type="hash", algorithm="md5")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0  # exit 0 even with FAIL items
        result = parse_json_output(out)
        assert result["summary"]["fail"] == 1

    def test_pass_count_in_summary(self):
        usages = [
            make_usage(type="hash", algorithm="sha256"),
            make_usage(name="second", type="hash", algorithm="sha512"),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["pass"] == 2

    def test_missing_name_exits_nonzero(self):
        usages = [{"type": "hash", "algorithm": "sha256"}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code != 0
        assert "ERROR" in err

    def test_unknown_type_exits_nonzero(self):
        usages = [make_usage(type="magic")]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code != 0
        assert "ERROR" in err

    def test_missing_algorithm_exits_nonzero(self):
        usages = [{"name": "x", "type": "hash"}]
        code, _, err = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code != 0
        assert "ERROR" in err

    def test_empty_input_exits_zero(self):
        code, out, _ = run_script(args=("-",), stdin_text="[]")
        assert code == 0

    def test_bad_json_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text="not json")
        assert code != 0
        assert "ERROR" in err

    def test_markdown_table_present(self):
        usages = [make_usage()]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        assert "Cryptographic Configuration Audit" in out

    def test_fail_items_section_present(self):
        usages = [make_usage(type="hash", algorithm="md5")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        assert "FAIL items" in out

    def test_fail_items_section_absent_when_all_pass(self):
        usages = [make_usage(type="hash", algorithm="sha256")]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        assert "FAIL items" not in out

    def test_file_path_argument(self, tmp_path):
        usages = [make_usage()]
        p = tmp_path / "crypto.json"
        p.write_text(json.dumps(usages))
        code, out, _ = run_script(args=(str(p),))
        assert code == 0

    def test_sorted_fail_first(self):
        usages = [
            make_usage(name="pass-item", type="hash", algorithm="sha256"),
            make_usage(name="fail-item", type="hash", algorithm="md5"),
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        result = parse_json_output(out)
        assert result["findings"][0]["name"] == "fail-item"

    def test_object_not_array_exits_nonzero(self):
        code, _, err = run_script(args=("-",), stdin_text='{"name":"x"}')
        assert code != 0

    def test_mixed_result_counts(self):
        usages = [
            make_usage(name="f1", type="hash", algorithm="md5"),  # FAIL
            make_usage(name="f2", type="hash", algorithm="sha256"),  # PASS
            make_usage(name="f3", type="kdf", algorithm="pbkdf2"),  # WARN
        ]
        code, out, _ = run_script(args=("-",), stdin_text=json.dumps(usages))
        assert code == 0
        result = parse_json_output(out)
        assert result["summary"]["fail"] == 1
        assert result["summary"]["pass"] == 1
        assert result["summary"]["warn"] == 1
