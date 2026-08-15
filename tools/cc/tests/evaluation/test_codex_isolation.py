from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import stat
import subprocess
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import cc.core.evaluation.codex_isolation as isolation
import pytest
from cc.core.evaluation.codex_isolation import (
    CodexIsolationUnavailable,
    authorize_codex_live_runtime,
    codex_isolation_receipt_document,
    probe_codex_isolation,
    retain_codex_live_dispatch,
    verify_codex_isolation_receipt,
    verify_codex_live_authorization,
    verify_codex_live_dispatch,
    verify_codex_live_dispatch_context,
    verify_codex_live_permit,
    verify_official_codex_registry_metadata,
)

PACKAGE_VERSION = "0.147.0"
MODEL = "gpt-5.6-sol"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog(path: Path) -> Path:
    value = {
        "client_version": PACKAGE_VERSION,
        "models": [
            {
                "slug": MODEL,
                "display_name": "Synthetic offline model",
                "apply_patch_tool_type": None,
                "experimental_supported_tools": [],
                "supports_search_tool": False,
                "supports_tool_suggest": False,
                "supports_skills": False,
                "supports_plugins": False,
                "supports_apps": False,
                "tool_mode": "direct",
                "use_responses_lite": False,
                "multi_agent_version": None,
                "model_messages": {
                    "instructions_template": "Synthetic offline model instructions."
                },
            }
        ],
    }
    path.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    path.chmod(0o600)
    return path


def _fake_codex(
    path: Path,
    *,
    behavior: str = "baseline",
    external_path: Path | None = None,
    process_marker: str = "",
) -> Path:
    source = textwrap.dedent(f"""\
        #!{sys.executable}
        import errno
        import http.client
        import json
        import os
        import pathlib
        import re
        import socket
        import subprocess
        import sys
        import time
        from urllib.parse import urlsplit

        BEHAVIOR = {behavior!r}
        EXTERNAL_PATH = {str(external_path) if external_path is not None else ''!r}
        PROCESS_MARKER = {process_marker!r}

        def spawn_descendant():
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    (
                        "import os, signal, time; "
                        "[os.close(fd) for fd in (0, 1, 2)]; "
                        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                        "time.sleep(60)"
                    ),
                    PROCESS_MARKER,
                ],
                close_fds=True,
            )

        if sys.argv[1:] == ["--version"]:
            if BEHAVIOR == "version-descendant":
                spawn_descendant()
            if BEHAVIOR == "version-output-flood":
                sys.stdout.write("x" * 16384)
                raise SystemExit(0)
            sys.stdout.write("codex-cli 0.147.0\\n")
            raise SystemExit(0)

        if any(name in os.environ for name in (
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY",
            "GITHUB_TOKEN", "GH_TOKEN",
        )):
            raise SystemExit(19)

        joined = " ".join(sys.argv)
        match = re.search(
            r'base_url="(http://127\\.0\\.0\\.1:[0-9]+/v1/[0-9a-f]{{64}})"',
            joined,
        )
        if match is None:
            raise SystemExit(20)
        endpoint = urlsplit(match.group(1))
        nonce = endpoint.path.rsplit("/", 1)[1]
        model = sys.argv[sys.argv.index("--model") + 1]
        work = pathlib.Path(sys.argv[sys.argv.index("-C") + 1])

        if BEHAVIOR == "external-network":
            try:
                connection = socket.create_connection(("1.1.1.1", 80), timeout=0.2)
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.EACCES):
                    raise SystemExit(21)
            else:
                connection.close()
                raise SystemExit(22)

        if BEHAVIOR == "external-write":
            try:
                pathlib.Path(EXTERNAL_PATH).write_text("forbidden", encoding="utf-8")
            except OSError as exc:
                if exc.errno not in (errno.EPERM, errno.EACCES):
                    raise SystemExit(23)
            else:
                raise SystemExit(24)

        body = {{
            "client_metadata": {{
                "turn_id": "01a00000-0000-7000-8000-000000000002",
                "x-codex-installation-id": "01a00000-0000-7000-8000-000000000003",
                "thread_id": "01a00000-0000-7000-8000-000000000001",
                "session_id": "01a00000-0000-7000-8000-000000000001",
                "x-codex-window-id": "01a00000-0000-7000-8000-000000000001:0",
                "x-codex-turn-metadata": json.dumps({{
                    "installation_id": "01a00000-0000-7000-8000-000000000003",
                    "session_id": "01a00000-0000-7000-8000-000000000001",
                    "thread_id": "01a00000-0000-7000-8000-000000000001",
                    "turn_id": "01a00000-0000-7000-8000-000000000002",
                    "window_id": "01a00000-0000-7000-8000-000000000001:0",
                    "request_kind": "turn",
                    "thread_source": "user",
                    "sandbox": "seatbelt",
                    "turn_started_at_unix_ms": 1,
                }}, separators=(",", ":")),
            }},
            "include": ["reasoning.encrypted_content"],
            "input": [
                {{
                    "type": "message",
                    "id": "msg_01a00000-0000-7000-8000-000000000004",
                    "role": "developer",
                    "content": [
                        {{
                            "type": "input_text",
                            "text": "<skills_instructions>\\nSynthetic.\\n</skills_instructions>",
                        }},
                        {{
                            "type": "input_text",
                            "text": "<permissions instructions>\\n`sandbox_mode` is `read-only`\\n</permissions instructions>",
                        }},
                    ],
                }},
                {{
                    "type": "message",
                    "id": "msg_01a00000-0000-7000-8000-000000000005",
                    "role": "user",
                    "content": [{{
                        "type": "input_text",
                        "text": (
                            "<environment_context>\\n"
                            f"  <cwd>{{work}}</cwd>\\n"
                            f"  <workspace_roots><root>{{work}}</root></workspace_roots>\\n"
                            "</environment_context>"
                        ),
                    }}],
                }},
                {{
                    "type": "message",
                    "id": "msg_01a00000-0000-7000-8000-000000000006",
                    "role": "user",
                    "content": [{{
                        "type": "input_text",
                        "text": "Return exactly OK. Do not call tools.",
                    }}],
                }},
            ],
            "instructions": "Synthetic offline model instructions.",
            "model": model,
            "parallel_tool_calls": True,
            "prompt_cache_key": "01a00000-0000-7000-8000-000000000001",
            "reasoning": {{"effort": "low"}},
            "store": False,
            "stream": True,
            "text": {{"verbosity": "low"}},
            "tool_choice": "auto",
            "tools": [],
        }}
        if BEHAVIOR == "extra-tool":
            body["tools"] = [{{"type": "function", "name": "shell"}}]
        if BEHAVIOR == "additional-tools":
            body["input"].insert(0, {{
                "type": "additional_tools",
                "role": "developer",
                "tools": [],
            }})
        if BEHAVIOR == "prompt-substitution":
            body["input"][-1]["content"][0]["text"] = "Substituted prompt"
        raw = b"{{" if BEHAVIOR == "malformed" else json.dumps(
            body, separators=(",", ":")
        ).encode("utf-8")
        if BEHAVIOR == "duplicate-tools":
            raw = raw.replace(
                b'"tools":[]',
                b'"tools":[{{"type":"function","name":"shell"}}],"tools":[]',
                1,
            )
        if BEHAVIOR == "duplicate-nested":
            raw = raw.replace(
                b'"reasoning":{{"effort":"low"}}',
                b'"reasoning":{{"effort":"high","effort":"low"}}',
                1,
            )

        def request_once(method="POST", path=None):
            connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=2)
            connection.request(
                method,
                path or endpoint.path + "/responses",
                body=raw if method == "POST" else None,
                headers={{
                    "Content-Type": "application/json",
                    "x-cc-isolation-nonce": (
                        "0" * 64 if BEHAVIOR == "nonce-substitution" else nonce
                    ),
                }},
            )
            response = connection.getresponse()
            response.read()
            connection.close()
            return response.status

        if BEHAVIOR == "get-before-post" and request_once("GET") != 400:
            raise SystemExit(25)
        if (
            BEHAVIOR == "extra-path"
            and request_once(path=endpoint.path + "/unexpected") != 400
        ):
            raise SystemExit(25)
        if request_once() != 400:
            raise SystemExit(25)
        if BEHAVIOR == "multiple" and request_once() != 400:
            raise SystemExit(26)

        if BEHAVIOR in ("request-descendant", "timeout-descendant"):
            spawn_descendant()
        if BEHAVIOR == "timeout-descendant":
            time.sleep(60)

        if BEHAVIOR == "staged-binary-replacement":
            current = pathlib.Path(sys.argv[0])
            retained = current.with_name("retained-codex")
            current.rename(retained)
            current.write_bytes(retained.read_bytes())
            current.chmod(0o755)
            retained.unlink()
        if BEHAVIOR == "staged-catalog-replacement":
            catalog_argument = next(
                item for item in sys.argv if item.startswith("model_catalog_json=")
            )
            current = pathlib.Path(json.loads(catalog_argument.split("=", 1)[1]))
            retained = current.with_name("retained-model-catalog.json")
            current.rename(retained)
            current.write_bytes(retained.read_bytes())
            current.chmod(0o600)
            retained.unlink()
        if BEHAVIOR == "unexpected-root-entry":
            (work.parent / "unexpected-sensitive").write_text(
                "synthetic-sensitive",
                encoding="utf-8",
            )
        if BEHAVIOR == "private-home-replacement":
            home = work.parent / "home"
            home.rename(work.parent / "retained-home")
            home.mkdir(mode=0o700)
        raise SystemExit(1)
        """)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture(autouse=True)
def _recognize_deterministic_test_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = isolation._native_format

    def recognize(raw: bytes) -> str:
        if raw.startswith(b"#!"):
            return "test-native-substitute"
        return original(raw)

    monkeypatch.setattr(isolation, "_native_format", recognize)


def _probe(
    binary: Path,
    catalog: Path,
    *,
    native_sha256: str | None = None,
    catalog_sha256: str | None = None,
):
    return probe_codex_isolation(
        binary,
        catalog,
        package_version=PACKAGE_VERSION,
        expected_native_sha256=native_sha256 or _digest(binary),
        expected_catalog_sha256=catalog_sha256 or _digest(catalog),
        model=MODEL,
    )


def _assert_cleared_roots(roots: list[Path]) -> None:
    assert roots
    for root in roots:
        assert root.is_dir()
        assert not any(root.iterdir())
        root.rmdir()


def _capture_temporary_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> list[Path]:
    roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)
    return roots


def _synthetic_official_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(isolation, "_native_format", lambda _raw: "mach-o")
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    receipt = _probe(binary, catalog)
    monkeypatch.setattr(
        isolation,
        "OFFICIAL_CODEX_NATIVE_SHA256",
        receipt.native_binary_sha256,
    )
    monkeypatch.setattr(
        isolation,
        "OFFICIAL_CODEX_NATIVE_BYTES",
        receipt.native_binary_bytes,
    )
    monkeypatch.setattr(
        isolation,
        "OFFICIAL_CODEX_CATALOG_SHA256",
        receipt.model_catalog_sha256,
    )
    package_policy = isolation.canonical_sha256(
        isolation._official_package_policy_document()
    )
    monkeypatch.setattr(
        isolation,
        "OFFICIAL_CODEX_PACKAGE_POLICY_SHA256",
        package_policy,
    )
    framework_release = isolation.canonical_sha256(
        isolation._official_framework_release_document()
    )
    monkeypatch.setattr(
        isolation,
        "OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY",
        framework_release,
    )
    authorization = authorize_codex_live_runtime(
        receipt,
        framework_release_identity=framework_release,
        expected_package_policy=package_policy,
    )
    return receipt, authorization, binary, catalog


def test_public_verifier_accepts_exact_single_request_with_no_visible_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    temporary_roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        temporary_roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)
    receipt = _probe(binary, catalog)

    assert receipt.validate()
    assert verify_codex_isolation_receipt(receipt)
    assert receipt.package_version == PACKAGE_VERSION
    assert receipt.native_binary_sha256 == _digest(binary)
    assert receipt.model_catalog_sha256 == _digest(catalog)
    assert receipt.request_count == 1
    assert receipt.model_visible_tools == ()
    assert receipt.response_path == "/v1/<NONCE>/responses"
    assert receipt.authorization_scope == "offline-measurement-only"
    assert receipt.live_runtime_authorized is False
    assert receipt.tool_registry_sha256 == isolation._TOOL_REGISTRY_SHA256
    _assert_cleared_roots(temporary_roots)

    document = codex_isolation_receipt_document(receipt)
    serialized = json.dumps(document, sort_keys=True)
    assert document["model_visible_tools"] == []
    assert "Return exactly OK" not in serialized
    assert "Synthetic offline model" not in serialized
    assert "input" not in document
    assert "headers" not in document
    assert set(document) == {
        "schema_version",
        "receipt_sha256",
        "package_version",
        "model",
        "authorization_scope",
        "live_runtime_authorized",
        "native_format",
        "native_binary_sha256",
        "native_binary_bytes",
        "model_catalog_sha256",
        "config_sha256",
        "config_contract_sha256",
        "argv_sha256",
        "argv_contract_sha256",
        "environment_sha256",
        "environment_contract_sha256",
        "sandbox_exec_sha256",
        "sandbox_contract_sha256",
        "sandbox_profile_sha256",
        "endpoint_sha256",
        "capture_nonce_sha256",
        "response_path",
        "request_sha256",
        "request_semantics_sha256",
        "transcript_sha256",
        "tool_registry_sha256",
        "request_count",
        "model_visible_tools",
    }


def test_self_asserted_package_measurement_never_authorizes_runtime_readiness(
    tmp_path: Path,
) -> None:
    receipt = _probe(
        _fake_codex(tmp_path / "codex"),
        _catalog(tmp_path / "codex-model-catalog.json"),
    )
    document = codex_isolation_receipt_document(receipt)

    assert receipt.validate()
    assert receipt.authorization_scope == "offline-measurement-only"
    assert receipt.live_runtime_authorized is False
    assert document["authorization_scope"] == "offline-measurement-only"
    assert document["live_runtime_authorized"] is False
    assert "official_package" not in document
    assert "runtime_ready" not in document


def test_frozen_official_release_record_covers_registry_sigstore_apple_and_source() -> (
    None
):
    registry = isolation._official_registry_document()
    policy = isolation._official_package_policy_document()

    assert (
        isolation.canonical_sha256(policy)
        == isolation.OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
    )
    assert (
        isolation.canonical_sha256(isolation._official_framework_release_document())
        == isolation.OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
    )
    assert registry["wrapper"]["dist"]["tarball_sha256"] == (
        "d28b4fd4bd9f07ea71083d0cc40c579595cebbd4c10bc8ca98a6d385432e7255"
    )
    assert registry["platform"]["dist"]["tarball_sha256"] == (
        "493de2d788c6ff01de222307c767231c1e6c802d5dd808523550fad6d972f4d3"
    )
    assert registry["platform"]["native_signature"] == {
        "signer": "Developer ID Application: OpenAI OpCo, LLC (2DC432GLL2)",
        "team_id": "2DC432GLL2",
    }
    for package in ("wrapper", "platform"):
        attestation = registry[package]["attestation"]
        assert attestation["predicate_type"] == "https://slsa.dev/provenance/v1"
        assert attestation["workflow"].endswith(
            "rust-release.yml@refs/tags/rust-v0.147.0"
        )
        assert attestation["repository_id"] == 965415649
        assert attestation["repository_owner_id"] == 14957082
        assert attestation["run_id"] == 31136011993
        assert attestation["run_attempt"] == 1
        assert attestation["conclusion"] == "success"
        signatures = registry[package]["dist"]["signatures"]
        assert len(signatures) == 2
        assert {item["keyid"] for item in signatures} == {
            "SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U"
        }
    source = policy["source_attribution"]
    assert source["tag_object"] == "3ed6f04f6bf8b7c46299d1cb1ff99c74ce21a51d"
    assert source["peeled_commit"] == "be6e8eac029b183056b7e4402879f15d2c85f61b"
    assert source["tree"] == "3828c818254d4c756585f5b59fe46b6fa3634765"
    assert source["tag_cryptographically_signed"] is False
    assert source["commit_cryptographically_signed"] is False
    assert source["authority"] == "attribution-only"


@pytest.mark.parametrize(
    "mutation",
    (
        "wrapper-signature",
        "platform-integrity",
        "attestation-workflow",
        "apple-team",
        "extra-field",
        "duplicate-key",
    ),
)
def test_release_time_registry_equality_rejects_provenance_drift(
    mutation: str,
) -> None:
    value = isolation._official_registry_document()
    if mutation == "wrapper-signature":
        value["wrapper"]["dist"]["signatures"][0]["sig"] = "substituted"
    elif mutation == "platform-integrity":
        value["platform"]["dist"]["integrity"] = "sha512-substituted"
    elif mutation == "attestation-workflow":
        value["platform"]["attestation"]["workflow"] = "substituted"
    elif mutation == "apple-team":
        value["platform"]["native_signature"]["team_id"] = "SUBSTITUTE"
    elif mutation == "extra-field":
        value["runtime_authorized"] = True
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if mutation == "duplicate-key":
        raw = raw.replace(
            b'"schema_version":',
            b'"schema_version":"substituted","schema_version":',
            1,
        )

    assert not verify_official_codex_registry_metadata(raw)


def test_release_time_registry_equality_accepts_only_the_frozen_projection() -> None:
    raw = json.dumps(
        isolation._official_registry_document(),
        separators=(",", ":"),
    ).encode("utf-8")

    assert verify_official_codex_registry_metadata(raw)


def test_one_shot_official_authorization_preserves_measurement_and_scopes_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    measurement_before = codex_isolation_receipt_document(receipt)
    temporary_roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        temporary_roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)

    assert receipt.authorization_scope == "offline-measurement-only"
    assert receipt.live_runtime_authorized is False
    assert authorization.live_runtime_authorized is True
    assert authorization.model_visible_tools == ()
    assert authorization.validate()
    assert verify_codex_live_authorization(authorization)

    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    permit = dispatch._state.permit

    assert not authorization.validate()
    assert dispatch.validate()
    assert verify_codex_live_dispatch(dispatch)
    assert permit.validate()
    assert verify_codex_live_permit(permit)
    assert permit.authorization_sha256 == authorization.authorization_sha256
    assert permit.measurement_receipt_sha256 == receipt.receipt_sha256
    assert permit.model_visible_tools == ()
    assert permit.live_runtime_authorized is True
    assert codex_isolation_receipt_document(receipt) == measurement_before
    seen_contexts = []

    def consume(context):
        assert context.validate()
        assert verify_codex_live_dispatch_context(context)
        assert context.native_binary.read_bytes() == binary.read_bytes()
        assert context.model_catalog.read_bytes() == catalog.read_bytes()
        assert context.model == MODEL
        seen_contexts.append(context)
        return "dispatched"

    assert dispatch.run_once(consume) == "dispatched"
    assert not dispatch.validate()
    assert not seen_contexts[0].validate()
    with pytest.raises(CodexIsolationUnavailable, match="already consumed"):
        dispatch.run_once(consume)
    with pytest.raises(CodexIsolationUnavailable, match="authorization or model"):
        retain_codex_live_dispatch(
            authorization,
            native_binary=binary,
            model_catalog=catalog,
            model=MODEL,
        )

    dispatch.close()
    dispatch.close()
    authorization.close()
    authorization.revoke()
    assert not permit.validate()
    assert receipt.validate()
    _assert_cleared_roots(temporary_roots)


def test_live_dispatch_public_claim_accepts_paths_and_never_caller_hashes() -> None:
    signature = inspect.signature(retain_codex_live_dispatch)

    assert tuple(signature.parameters) == (
        "authorization",
        "native_binary",
        "model_catalog",
        "model",
    )
    assert all(
        "sha" not in name and "digest" not in name for name in signature.parameters
    )


def test_live_dispatch_callback_failure_closes_every_capability_and_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    roots = _capture_temporary_roots(monkeypatch)
    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    permit = dispatch._state.permit
    contexts = []

    def fail(context):
        contexts.append(context)
        assert context.validate()
        raise RuntimeError("synthetic adapter failure")

    with pytest.raises(RuntimeError, match="synthetic adapter failure"):
        dispatch.run_once(fail)

    assert receipt.validate()
    assert not permit.validate()
    assert not dispatch.validate()
    assert not contexts[0].validate()
    with pytest.raises(CodexIsolationUnavailable, match="already consumed"):
        dispatch.run_once(fail)
    _assert_cleared_roots(roots)


@pytest.mark.parametrize("mutation", ("staged-native", "extra-entry", "source-swap"))
def test_live_dispatch_revalidates_after_callback_and_clears_private_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    roots = _capture_temporary_roots(monkeypatch)
    replacement = b"harmless source replacement"

    def mutate(context):
        if mutation == "staged-native":
            context.native_binary.chmod(0o700)
        elif mutation == "extra-entry":
            (context.native_binary.parent / "unexpected").write_bytes(b"sensitive")
        else:
            binary.rename(tmp_path / "displaced-codex")
            binary.write_bytes(replacement)
            binary.chmod(0o755)

    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    with pytest.raises(CodexIsolationUnavailable, match="changed during"):
        dispatch.run_once(mutate)

    assert not dispatch.validate()
    if mutation == "source-swap":
        assert binary.read_bytes() == replacement
        assert (tmp_path / "displaced-codex").is_file()
    _assert_cleared_roots(roots)


@pytest.mark.parametrize(
    "substitution", ("symlink", "hardlink", "mode", "name", "string")
)
def test_live_dispatch_rejects_unretained_or_inexact_input_paths_without_consuming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    replacement = tmp_path / substitution
    replacement.mkdir()
    native_binary: Path | str = replacement / "codex"
    if substitution == "symlink":
        native_binary.symlink_to(binary)
    elif substitution == "hardlink":
        os.link(binary, native_binary)
    else:
        native_binary.write_bytes(binary.read_bytes())
        native_binary.chmod(0o755)
        if substitution == "mode":
            native_binary.chmod(0o700)
        elif substitution == "name":
            renamed = replacement / "not-codex"
            native_binary.rename(renamed)
            native_binary = renamed
        elif substitution == "string":
            native_binary = str(native_binary)

    with pytest.raises(
        CodexIsolationUnavailable,
        match="canonical|identity|authorization|retained safely",
    ):
        retain_codex_live_dispatch(
            authorization,
            native_binary=native_binary,  # type: ignore[arg-type]
            model_catalog=catalog,
            model=MODEL,
        )
    assert authorization.validate()


def test_live_dispatch_rejects_source_swap_before_atomic_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    roots = _capture_temporary_roots(monkeypatch)
    original_stage = isolation._stage_file_at
    replacement = b"harmless replacement"
    called = False

    def swap_then_stage(*args, **kwargs):
        nonlocal called
        if not called:
            called = True
            binary.rename(tmp_path / "retained-original")
            binary.write_bytes(replacement)
            binary.chmod(0o755)
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(isolation, "_stage_file_at", swap_then_stage)
    with pytest.raises(
        CodexIsolationUnavailable, match="changed during private staging"
    ):
        retain_codex_live_dispatch(
            authorization,
            native_binary=binary,
            model_catalog=catalog,
            model=MODEL,
        )

    assert authorization.validate()
    assert binary.read_bytes() == replacement
    assert (tmp_path / "retained-original").is_file()
    _assert_cleared_roots(roots)


def test_live_dispatch_cannot_be_closed_from_inside_active_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    roots = _capture_temporary_roots(monkeypatch)
    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )

    with pytest.raises(CodexIsolationUnavailable, match="cannot close"):
        dispatch.run_once(lambda _context: dispatch.close())

    assert not dispatch.validate()
    _assert_cleared_roots(roots)


def test_live_dispatch_reentrant_run_never_enters_second_callback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    roots = _capture_temporary_roots(monkeypatch)
    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    permit = dispatch._state.permit
    outer_contexts = []
    inner_calls = 0

    def inner(_context):
        nonlocal inner_calls
        inner_calls += 1

    def outer(context):
        outer_contexts.append(context)
        with pytest.raises(CodexIsolationUnavailable, match="already consumed"):
            dispatch.run_once(inner)
        assert context.validate()
        return "outer-only"

    assert dispatch.run_once(outer) == "outer-only"
    assert inner_calls == 0
    assert not outer_contexts[0].validate()
    assert not permit.validate()
    assert not dispatch.validate()
    _assert_cleared_roots(roots)


def test_authorization_and_permit_copy_deepcopy_replace_are_not_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    assert not verify_codex_live_authorization(copy.copy(authorization))
    assert not verify_codex_live_authorization(copy.deepcopy(authorization))
    assert not verify_codex_live_authorization(replace(authorization))
    copied_authorization = copy.copy(authorization)
    copied_authorization.close()
    assert authorization.validate()
    with pytest.raises(CodexIsolationUnavailable, match="authorization or model"):
        retain_codex_live_dispatch(
            copied_authorization,
            native_binary=binary,
            model_catalog=catalog,
            model=MODEL,
        )
    assert authorization.validate()

    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    permit = dispatch._state.permit
    copied_dispatch = copy.copy(dispatch)
    copied_dispatch.close()
    assert dispatch.validate()
    assert not verify_codex_live_dispatch(copied_dispatch)
    deepcopied_dispatch = copy.deepcopy(dispatch)
    deepcopied_dispatch.close()
    replaced_dispatch = replace(dispatch)
    replaced_dispatch.close()
    assert dispatch.validate()
    assert not verify_codex_live_dispatch(deepcopied_dispatch)
    assert not verify_codex_live_dispatch(replaced_dispatch)
    copied = copy.copy(permit)
    copied.close()
    assert permit.validate()
    assert not verify_codex_live_permit(copied)
    assert not verify_codex_live_permit(copy.deepcopy(permit))
    assert not verify_codex_live_permit(replace(permit))

    def inspect_context(context):
        assert not verify_codex_live_dispatch_context(copy.copy(context))
        assert not verify_codex_live_dispatch_context(copy.deepcopy(context))
        assert not verify_codex_live_dispatch_context(replace(context))

    dispatch.run_once(inspect_context)
    assert not permit.validate()


def test_closing_measurement_revokes_active_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    dispatch = retain_codex_live_dispatch(
        authorization,
        native_binary=binary,
        model_catalog=catalog,
        model=MODEL,
    )
    permit = dispatch._state.permit
    receipt.close()

    assert not permit.validate()
    assert not dispatch.validate()
    with pytest.raises(CodexIsolationUnavailable, match="unavailable"):
        dispatch.run_once(lambda _context: None)
    dispatch.close()


def test_frozen_release_contract_mutation_revokes_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(isolation, "OFFICIAL_CODEX_MODEL", "substituted-model")

    assert not authorization.validate()
    with pytest.raises(CodexIsolationUnavailable, match="contract source changed"):
        retain_codex_live_dispatch(
            authorization,
            native_binary=binary,
            model_catalog=catalog,
            model="substituted-model",
        )


@pytest.mark.parametrize(
    "substitution",
    (
        "framework",
        "package-policy",
        "native",
        "catalog",
        "model",
        "receipt-closed",
    ),
)
def test_authorization_and_consumption_reject_identity_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    substitution: str,
) -> None:
    receipt, authorization, binary, catalog = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    if substitution in {"framework", "package-policy"}:
        (tmp_path / "second").mkdir()
        second_receipt = _probe(
            _fake_codex(tmp_path / "second" / "codex"),
            _catalog(tmp_path / "second" / "codex-model-catalog.json"),
        )
        kwargs = {
            "framework_release_identity": (
                "0" * 64
                if substitution == "framework"
                else isolation.OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            ),
            "expected_package_policy": (
                "0" * 64
                if substitution == "package-policy"
                else isolation.OFFICIAL_CODEX_PACKAGE_POLICY_SHA256
            ),
        }
        with pytest.raises(CodexIsolationUnavailable, match="official package policy"):
            authorize_codex_live_runtime(second_receipt, **kwargs)
        assert authorization.validate()
        return

    native_binary = binary
    model_catalog = catalog
    model = MODEL
    if substitution == "native":
        replacement = tmp_path / "substituted-native"
        replacement.mkdir()
        native_binary = _fake_codex(replacement / "codex")
        native_binary.write_bytes(native_binary.read_bytes() + b"substituted")
    elif substitution == "catalog":
        replacement = tmp_path / "substituted-catalog"
        replacement.mkdir()
        model_catalog = _catalog(replacement / "codex-model-catalog.json")
        model_catalog.write_bytes(model_catalog.read_bytes() + b" ")
    elif substitution == "model":
        model = "substituted-model"
    else:
        receipt.close()

    with pytest.raises(CodexIsolationUnavailable, match="differs|unavailable"):
        retain_codex_live_dispatch(
            authorization,
            native_binary=native_binary,
            model_catalog=model_catalog,
            model=model,
        )
    assert authorization.validate() is (substitution != "receipt-closed")


def test_measurement_can_authorize_only_once_even_after_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, authorization, _binary, _catalog_path = _synthetic_official_authorization(
        tmp_path,
        monkeypatch,
    )
    authorization.close()

    with pytest.raises(CodexIsolationUnavailable, match="already bound"):
        authorize_codex_live_runtime(
            receipt,
            framework_release_identity=(
                isolation.OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            ),
            expected_package_policy=isolation.OFFICIAL_CODEX_PACKAGE_POLICY_SHA256,
        )


def test_plain_self_asserted_measurement_cannot_match_official_release(
    tmp_path: Path,
) -> None:
    receipt = _probe(
        _fake_codex(tmp_path / "codex"),
        _catalog(tmp_path / "codex-model-catalog.json"),
    )

    with pytest.raises(CodexIsolationUnavailable, match="official package policy"):
        authorize_codex_live_runtime(
            receipt,
            framework_release_identity=(
                isolation.OFFICIAL_CODEX_FRAMEWORK_RELEASE_IDENTITY
            ),
            expected_package_policy=isolation.OFFICIAL_CODEX_PACKAGE_POLICY_SHA256,
        )


@pytest.mark.parametrize(
    ("behavior", "message"),
    (
        ("extra-tool", "no-tools contract"),
        ("additional-tools", "input is not exact"),
        ("prompt-substitution", "no-tools contract"),
        ("nonce-substitution", "no-tools contract"),
        ("malformed", "no-tools contract"),
        ("duplicate-tools", "no-tools contract"),
        ("duplicate-nested", "no-tools contract"),
        ("multiple", "exactly one"),
        ("get-before-post", "exactly one"),
        ("extra-path", "exactly one"),
        ("private-home-replacement", "request probe failed"),
        ("staged-binary-replacement", "changed before evidence"),
        ("staged-catalog-replacement", "changed before evidence"),
    ),
)
def test_verifier_rejects_request_and_retained_input_substitution(
    tmp_path: Path,
    behavior: str,
    message: str,
) -> None:
    binary = _fake_codex(tmp_path / "codex", behavior=behavior)
    catalog = _catalog(tmp_path / "codex-model-catalog.json")

    with pytest.raises(CodexIsolationUnavailable, match=message):
        _probe(binary, catalog)


@pytest.mark.parametrize("target", ("binary", "catalog"))
def test_expected_binary_and_catalog_digest_swaps_fail_closed(
    tmp_path: Path,
    target: str,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    kwargs = {
        "native_sha256": "0" * 64 if target == "binary" else None,
        "catalog_sha256": "0" * 64 if target == "catalog" else None,
    }

    with pytest.raises(CodexIsolationUnavailable, match="digest differs"):
        _probe(binary, catalog, **kwargs)


def test_self_consistent_catalog_with_apply_patch_is_rejected(tmp_path: Path) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    value = json.loads(catalog.read_text(encoding="utf-8"))
    value["models"][0]["apply_patch_tool_type"] = "freeform"
    catalog.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(CodexIsolationUnavailable, match="suppress"):
        _probe(binary, catalog)


@pytest.mark.parametrize(
    ("field_name", "replacement", "remove"),
    (
        ("use_responses_lite", True, False),
        ("use_responses_lite", None, True),
        ("tool_mode", "code_mode_only", False),
        ("tool_mode", None, True),
        ("multi_agent_version", "v2", False),
        ("multi_agent_version", None, True),
    ),
)
def test_catalog_must_pin_direct_non_lite_and_no_multi_agent(
    tmp_path: Path,
    field_name: str,
    replacement: object,
    remove: bool,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    value = json.loads(catalog.read_text(encoding="utf-8"))
    if remove:
        value["models"][0].pop(field_name)
    else:
        value["models"][0][field_name] = replacement
    catalog.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

    with pytest.raises(CodexIsolationUnavailable, match="suppress"):
        _probe(binary, catalog)


@pytest.mark.parametrize(
    "endpoint",
    (
        "https://127.0.0.1:443/v1",
        "http://localhost:8000/v1",
        "http://1.1.1.1:8000/v1",
        "http://127.0.0.1:8000/v2",
        "http://user@127.0.0.1:8000/v1",
    ),
)
def test_external_or_noncanonical_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises(CodexIsolationUnavailable, match="loopback"):
        isolation._require_loopback_endpoint(endpoint, nonce="a" * 64)


@pytest.mark.parametrize(
    ("target", "mutation"),
    (
        ("binary", "symlink"),
        ("binary", "hardlink"),
        ("binary", "mode"),
        ("binary", "name"),
        ("catalog", "symlink"),
        ("catalog", "hardlink"),
        ("catalog", "mode"),
        ("catalog", "name"),
    ),
)
def test_input_symlink_hardlink_mode_and_name_swaps_are_rejected(
    tmp_path: Path,
    target: str,
    mutation: str,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    selected = binary if target == "binary" else catalog
    if mutation == "symlink":
        retained = selected.with_name(f"retained-{selected.name}")
        selected.rename(retained)
        selected.symlink_to(retained.name)
    elif mutation == "hardlink":
        os.link(selected, tmp_path / f"second-{selected.name}")
    elif mutation == "mode":
        selected.chmod(0o700 if target == "binary" else 0o640)
    else:
        renamed = selected.with_name(f"renamed-{selected.name}")
        selected.rename(renamed)
        if target == "binary":
            binary = renamed
        else:
            catalog = renamed

    with pytest.raises(
        CodexIsolationUnavailable,
        match="name|ownership|regular|retained safely",
    ):
        _probe(binary, catalog)


@pytest.mark.parametrize("contract", ("config", "argv", "environment", "sandbox"))
def test_internal_config_argv_environment_and_sandbox_swaps_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract: str,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    if contract == "config":
        changed = copy.deepcopy(isolation._CONFIG_CONTRACT)
        changed["sandbox"] = "danger-full-access"
        monkeypatch.setattr(isolation, "_CONFIG_CONTRACT", changed)
    elif contract == "argv":
        monkeypatch.setattr(
            isolation,
            "_DISABLED_FEATURES",
            tuple(
                item for item in isolation._DISABLED_FEATURES if item != "shell_tool"
            ),
        )
    elif contract == "environment":
        changed = dict(isolation._ENVIRONMENT_CONTRACT)
        changed["OPENAI_API_KEY"] = "<CREDENTIAL>"
        monkeypatch.setattr(isolation, "_ENVIRONMENT_CONTRACT", changed)
    else:
        monkeypatch.setattr(
            isolation,
            "_SANDBOX_PROFILE_TEMPLATE",
            isolation._SANDBOX_PROFILE_TEMPLATE.replace("(deny network*)\n", ""),
        )

    with pytest.raises(CodexIsolationUnavailable, match="contract source changed"):
        _probe(binary, catalog)


def test_actual_private_environment_paths_cannot_be_substituted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    outside = {
        name: tmp_path / f"outside-{name.lower()}"
        for name in ("HOME", "CODEX_HOME", "TMPDIR")
    }
    for path in outside.values():
        path.mkdir(mode=0o700)
    original_environment = isolation._private_environment

    def substituted_environment(root: Path) -> dict[str, str]:
        value = original_environment(root)
        value.update({name: str(path) for name, path in outside.items()})
        return value

    monkeypatch.setattr(isolation, "_private_environment", substituted_environment)

    with pytest.raises(CodexIsolationUnavailable, match="environment identity"):
        _probe(binary, catalog)

    assert all(path.is_dir() for path in outside.values())


def test_receipt_copy_deepcopy_and_replace_cannot_reuse_authority(
    tmp_path: Path,
) -> None:
    receipt = _probe(
        _fake_codex(tmp_path / "codex"),
        _catalog(tmp_path / "codex-model-catalog.json"),
    )

    assert not verify_codex_isolation_receipt(copy.copy(receipt))
    assert not verify_codex_isolation_receipt(copy.deepcopy(receipt))
    assert not verify_codex_isolation_receipt(replace(receipt))
    copied = copy.copy(receipt)
    copied.close()
    assert receipt.validate()
    altered = replace(receipt, request_sha256="0" * 64)
    assert not verify_codex_isolation_receipt(altered)


def test_os_policy_blocks_external_network_without_preventing_loopback(
    tmp_path: Path,
) -> None:
    receipt = _probe(
        _fake_codex(tmp_path / "codex", behavior="external-network"),
        _catalog(tmp_path / "codex-model-catalog.json"),
    )

    assert receipt.validate()


def test_minimal_environment_and_file_policy_block_credentials_and_external_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external = tmp_path / "outside-probe-artifact.json"
    binary = _fake_codex(
        tmp_path / "codex",
        behavior="external-write",
        external_path=external,
    )
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-process-boundary")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-cross-process-boundary")

    receipt = _probe(binary, catalog)

    assert receipt.validate()
    assert not external.exists()


def _process_with_marker_exists(marker: str) -> bool:
    completed = subprocess.run(
        ["/bin/ps", "-ax", "-o", "command="],
        check=True,
        capture_output=True,
        text=True,
    )
    return marker in completed.stdout


def test_reaped_process_group_never_signals_a_reused_numeric_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, int]] = []

    class ReapedProcess:
        pid = 424_242
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            raise AssertionError(f"stale process waited with {timeout}")

    monkeypatch.setattr(
        isolation.os,
        "killpg",
        lambda process_group, sent: signals.append((process_group, sent)),
    )

    with pytest.raises(CodexIsolationUnavailable, match="reaped before cleanup"):
        isolation._terminate_process_group(ReapedProcess())

    assert signals == []


def test_process_group_leader_is_waited_once_after_the_last_group_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class RetainedProcess:
        pid = 424_243
        returncode = None

        def wait(self, *, timeout: float) -> int:
            events.append(f"wait:{timeout}")
            self.returncode = 0
            return 0

    process = RetainedProcess()
    monkeypatch.setattr(
        isolation.os,
        "killpg",
        lambda process_group, sent: events.append(f"killpg:{process_group}:{sent}"),
    )
    monkeypatch.setattr(
        isolation,
        "_retained_process_group_state",
        lambda _group: events.append("retained-group-inspected")
        or (True, False, False),
    )

    assert (
        isolation._terminate_process_group(
            process,
            process_group_verified=True,
        )
        == 0
    )
    assert events[-1].startswith("wait:")
    assert sum(item.startswith("wait:") for item in events) == 1


@pytest.mark.parametrize("_repeat", range(10))
def test_rapid_successful_probe_cleanup_never_uses_a_stale_process_group(
    tmp_path: Path,
    _repeat: int,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")

    assert _probe(binary, catalog).validate()


@pytest.mark.parametrize("behavior", ("version-descendant", "request-descendant"))
def test_process_group_cleanup_reaps_descendants_on_every_successful_exit(
    tmp_path: Path,
    behavior: str,
) -> None:
    marker = f"cc-isolation-{behavior}-{tmp_path.name}"
    binary = _fake_codex(
        tmp_path / "codex",
        behavior=behavior,
        process_marker=marker,
    )
    catalog = _catalog(tmp_path / "codex-model-catalog.json")

    receipt = _probe(binary, catalog)

    assert receipt.validate()
    assert not _process_with_marker_exists(marker)


def test_timeout_kills_and_reaps_direct_process_and_term_ignoring_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = f"cc-isolation-timeout-{tmp_path.name}"
    binary = _fake_codex(
        tmp_path / "codex",
        behavior="timeout-descendant",
        process_marker=marker,
    )
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    temporary_roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        temporary_roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation, "_REQUEST_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)

    with pytest.raises(CodexIsolationUnavailable, match="request probe failed"):
        _probe(binary, catalog)

    assert not _process_with_marker_exists(marker)
    _assert_cleared_roots(temporary_roots)


def test_version_output_is_bounded_and_private_root_is_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(
        tmp_path / "codex",
        behavior="version-output-flood",
    )
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    temporary_roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        temporary_roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)

    with pytest.raises(CodexIsolationUnavailable, match="output exceeded"):
        _probe(binary, catalog)

    _assert_cleared_roots(temporary_roots)


def test_aggregate_capture_bytes_are_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    changed = copy.deepcopy(isolation._CONFIG_CONTRACT)
    changed["capture_policy"]["maximum_aggregate_body_bytes"] = 128
    monkeypatch.setattr(isolation, "_MAX_CAPTURE_BYTES", 128)
    monkeypatch.setattr(isolation, "_CONFIG_CONTRACT", changed)
    monkeypatch.setattr(
        isolation,
        "_CONFIG_CONTRACT_SHA256",
        isolation.canonical_sha256(changed),
    )

    with pytest.raises(CodexIsolationUnavailable, match="exactly one"):
        _probe(binary, catalog)


def test_retained_private_root_rejects_mode_extra_and_path_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    retained = isolation._RetainedPrivateRoot(root.resolve(), ())
    assert retained.validate()

    root.chmod(0o750)
    assert not retained.validate()
    root.chmod(0o700)
    extra = root / "extra"
    extra.write_text("extra", encoding="utf-8")
    assert not retained.validate()
    extra.unlink()
    original = tmp_path / "retained-original"
    root.rename(original)
    root.mkdir(mode=0o700)
    assert not retained.validate()
    root.rmdir()
    original.rename(root)

    retained.remove()
    retained.close()
    assert root.is_dir() and not any(root.iterdir())
    root.rmdir()


def test_retained_root_cleanup_uses_exact_inode_despite_mode_and_content_drift(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    retained = isolation._RetainedPrivateRoot(root.resolve(), ())
    root.chmod(0o750)
    (root / "unexpected-sensitive").write_text(
        "synthetic-sensitive",
        encoding="utf-8",
    )

    assert not retained.validate()
    assert retained.validate_identity()

    retained.remove()
    retained.close()
    assert root.is_dir() and not any(root.iterdir())
    root.rmdir()


def test_descriptor_cleanup_never_touches_a_same_uid_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-root"
    root.mkdir(mode=0o700)
    (root / "original-sensitive").write_text("clear-me", encoding="utf-8")
    retained = isolation._RetainedPrivateRoot(root.resolve(), ("original-sensitive",))
    displaced = tmp_path / "retained-original"
    replacement = tmp_path / "replacement"
    replacement.mkdir(mode=0o700)
    victim = replacement / "victim"
    victim.write_text("preserve", encoding="utf-8")
    replacement_inode = replacement.stat().st_ino
    root.rename(displaced)
    replacement.rename(root)

    retained.remove()

    assert root.stat().st_ino == replacement_inode
    assert (root / "victim").read_text(encoding="utf-8") == "preserve"
    assert displaced.stat().st_ino == retained.root_identity[1]
    assert not any(displaced.iterdir())
    retained.close()
    (root / "victim").unlink()
    root.rmdir()
    displaced.rmdir()


def test_constructor_path_swap_never_deletes_the_replacement_victim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    original_mkdtemp = isolation.tempfile.mkdtemp
    displaced: list[Path] = []
    replacements: list[Path] = []

    def local_mkdtemp(*args, **kwargs):
        kwargs["dir"] = tmp_path
        return original_mkdtemp(*args, **kwargs)

    def swap_before_retention(path: Path, _entries: tuple[str, ...]):
        original = path.with_name(f"{path.name}-displaced")
        path.rename(original)
        path.mkdir(mode=0o700)
        (path / "victim").write_text("preserve", encoding="utf-8")
        displaced.append(original)
        replacements.append(path)
        raise CodexIsolationUnavailable("synthetic pre-retention swap")

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", local_mkdtemp)
    monkeypatch.setattr(isolation, "_RetainedPrivateRoot", swap_before_retention)

    with pytest.raises(CodexIsolationUnavailable, match="pre-retention swap"):
        _probe(binary, catalog)

    assert displaced and displaced[0].is_dir()
    assert replacements and (replacements[0] / "victim").read_text() == "preserve"


def test_unexpected_probe_entry_rejects_issuance_but_is_still_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(
        tmp_path / "codex",
        behavior="unexpected-root-entry",
    )
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    temporary_roots: list[Path] = []
    original_mkdtemp = isolation.tempfile.mkdtemp

    def retained_mkdtemp(*args, **kwargs):
        result = Path(original_mkdtemp(*args, **kwargs))
        temporary_roots.append(result)
        return str(result)

    monkeypatch.setattr(isolation.tempfile, "mkdtemp", retained_mkdtemp)

    with pytest.raises(CodexIsolationUnavailable, match="request probe failed"):
        _probe(binary, catalog)

    _assert_cleared_roots(temporary_roots)


def test_version_and_native_format_fail_closed_before_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")
    monkeypatch.undo()

    with pytest.raises(CodexIsolationUnavailable, match="native binary"):
        _probe(binary, catalog)

    monkeypatch.setattr(isolation, "_native_format", lambda _raw: "test-native")
    with pytest.raises(CodexIsolationUnavailable, match="below 0.147.0"):
        probe_codex_isolation(
            binary,
            catalog,
            package_version="0.146.0",
            expected_native_sha256=_digest(binary),
            expected_catalog_sha256=_digest(catalog),
            model=MODEL,
        )


def test_input_modes_are_exact_in_baseline(tmp_path: Path) -> None:
    binary = _fake_codex(tmp_path / "codex")
    catalog = _catalog(tmp_path / "codex-model-catalog.json")

    assert stat.S_IMODE(binary.stat().st_mode) == 0o755
    assert stat.S_IMODE(catalog.stat().st_mode) == 0o600
    assert _probe(binary, catalog).validate()
