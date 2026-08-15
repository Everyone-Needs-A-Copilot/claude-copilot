from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import cc.core.evaluation.codex_isolation as isolation
import pytest
from cc.core.evaluation.live_runtime import (
    _CODEX_LIVE_DISABLED_FEATURES,
    CodexNonInteractiveAdapter,
    RuntimeTerminalFailure,
)
from cc.core.evaluation.models import RuntimeName
from test_live_runtime import (
    _adapter_cell,
    _codex_prompt_packet,
    _codex_source,
    _codex_stream,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _Dispatch:
    def __init__(self, native: Path, catalog: Path, model: str) -> None:
        self.model = model
        self.native_binary_sha256 = _digest(native)
        self.model_catalog_sha256 = _digest(catalog)
        self.dispatch_sha256 = "1" * 64
        self.authorization_sha256 = "2" * 64
        self.permit_sha256 = "3" * 64
        self.framework_release_identity = "4" * 64
        self.package_policy_sha256 = "5" * 64
        self.measurement_receipt_sha256 = "6" * 64
        self.tool_registry_sha256 = "7" * 64
        self.context = SimpleNamespace(
            context_sha256="8" * 64,
            dispatch_sha256=self.dispatch_sha256,
            authorization_sha256=self.authorization_sha256,
            permit_sha256=self.permit_sha256,
            native_binary=native,
            model_catalog=catalog,
            model=model,
        )
        self.active = True
        self.running = False
        self.run_calls = 0
        self.close_calls = 0

    def run_once(self, callback):
        if not self.active or self.running:
            raise isolation.CodexIsolationUnavailable("synthetic dispatch unavailable")
        self.run_calls += 1
        self.running = True
        try:
            return callback(self.context)
        finally:
            self.running = False
            self.active = False

    def close(self) -> None:
        self.close_calls += 1
        self.active = False


def _inputs(tmp_path: Path):
    tmp_path.chmod(0o700)
    original = tmp_path / "official-codex"
    original.write_bytes(b"synthetic official codex")
    original.chmod(0o700)
    dispatch_root = tmp_path / "dispatch-inputs"
    dispatch_root.mkdir(mode=0o700)
    native = dispatch_root / "codex"
    native.write_bytes(original.read_bytes())
    native.chmod(0o700)
    catalog = dispatch_root / "codex-model-catalog.json"
    catalog.write_text('{"synthetic":"no-tools"}', encoding="utf-8")
    catalog.chmod(0o600)
    auth = tmp_path / "auth.json"
    auth.write_text('{"synthetic":"credential"}', encoding="utf-8")
    auth.chmod(0o600)
    return original, native, catalog, auth


def _patch_verifiers(
    monkeypatch: pytest.MonkeyPatch,
    dispatch: _Dispatch,
) -> None:
    issued_context = dispatch.context
    monkeypatch.setattr(
        isolation,
        "verify_codex_live_dispatch",
        lambda value: value is dispatch and dispatch.active and not dispatch.running,
    )
    monkeypatch.setattr(
        isolation,
        "verify_codex_live_dispatch_context",
        lambda value: (
            value is issued_context and dispatch.active and dispatch.running
        ),
    )


def test_codex_adapter_consumes_one_retained_dispatch_and_binds_exact_catalog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, native, catalog, auth = _inputs(tmp_path)
    dispatch = _Dispatch(native, catalog, "test-model")
    _patch_verifiers(monkeypatch, dispatch)
    packet = _codex_prompt_packet()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert Path(argv[0]) == native
        assert argv[1:4] == ["--ask-for-approval", "never", "exec"]
        assert "--ignore-user-config" in argv
        assert "--ignore-rules" in argv
        assert "--skip-git-repo-check" in argv
        assert argv[argv.index("--model") + 1] == "test-model"
        configured_catalogs = [
            argv[index + 1]
            for index, value in enumerate(argv)
            if value == "-c" and "model_catalog_json=" in argv[index + 1]
        ]
        assert configured_catalogs == [f"model_catalog_json={json.dumps(str(catalog))}"]
        disabled = {
            argv[index + 1] for index, value in enumerate(argv) if value == "--disable"
        }
        assert disabled == set(_CODEX_LIVE_DISABLED_FEATURES)
        final_path = Path(argv[argv.index("--output-last-message") + 1])
        final_path.write_text("Synthetic evidence-bound result.", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, _codex_stream(), "")

    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=original,
        run=run,
        source_resolver=_codex_source,
        auth_source=auth,
        live_dispatch=dispatch,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        original,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    output = adapter.execute(cell)

    assert len(calls) == 1
    assert dispatch.run_calls == 1
    assert dispatch.close_calls == 1
    assert not dispatch.active
    assert (tmp_path / output.controlled_artifact_path).read_text() == (
        "Synthetic evidence-bound result."
    )
    execution = json.loads(output.completion_receipt._execution_policy_document)
    assert execution["live_dispatch"] == {
        "context_sha256": dispatch.context.context_sha256,
        "dispatch_sha256": dispatch.dispatch_sha256,
        "authorization_sha256": dispatch.authorization_sha256,
        "permit_sha256": dispatch.permit_sha256,
        "native_binary_sha256": _digest(native),
        "model_catalog_sha256": _digest(catalog),
        "model": "test-model",
    }
    with pytest.raises(RuntimeTerminalFailure, match="runtime-input-changed"):
        adapter.execute(cell)
    assert len(calls) == 1
    assert dispatch.run_calls == 1


def test_codex_adapter_rejects_substituted_dispatch_context_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, native, catalog, auth = _inputs(tmp_path)
    dispatch = _Dispatch(native, catalog, "test-model")
    _patch_verifiers(monkeypatch, dispatch)
    packet = _codex_prompt_packet()
    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=original,
        run=lambda *_args, **_kwargs: pytest.fail("subprocess must not start"),
        source_resolver=_codex_source,
        auth_source=auth,
        live_dispatch=dispatch,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        original,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )
    dispatch.context = SimpleNamespace(**dispatch.context.__dict__)

    with pytest.raises(RuntimeTerminalFailure, match="runtime-input-changed"):
        adapter.execute(cell)

    assert dispatch.run_calls == 1
    assert dispatch.close_calls == 1
    assert not tuple(tmp_path.glob("runtime-quarantine/*.txt"))


def test_codex_adapter_closes_dispatch_when_callback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, native, catalog, auth = _inputs(tmp_path)
    dispatch = _Dispatch(native, catalog, "test-model")
    _patch_verifiers(monkeypatch, dispatch)
    packet = _codex_prompt_packet()

    def fail(*_args, **_kwargs):
        raise OSError("synthetic child failure")

    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=original,
        run=fail,
        source_resolver=_codex_source,
        auth_source=auth,
        live_dispatch=dispatch,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        original,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    with pytest.raises(RuntimeTerminalFailure, match="runtime-executable-failure"):
        adapter.execute(cell)

    assert dispatch.run_calls == 1
    assert dispatch.close_calls == 1
    assert not dispatch.active
    assert not tuple(tmp_path.glob("runtime-quarantine/*.txt"))


def test_codex_production_consumer_stays_unsupported_before_live_launch_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original, native, catalog, auth = _inputs(tmp_path)
    dispatch = _Dispatch(native, catalog, "test-model")
    _patch_verifiers(monkeypatch, dispatch)
    packet = _codex_prompt_packet()
    adapter = CodexNonInteractiveAdapter(
        packet,
        model="test-model",
        artifact_root=tmp_path,
        executable=original,
        source_resolver=_codex_source,
        auth_source=auth,
        live_dispatch=dispatch,
    )
    cell = _adapter_cell(
        RuntimeName.CODEX,
        original,
        packet,
        adapter.tool_configuration_sha256,
        adapter.effective_full_prompt_sha256,
        adapter.command_policy_sha256,
    )

    with pytest.raises(
        RuntimeTerminalFailure,
        match="codex-no-tool-isolation-unavailable",
    ):
        adapter.execute(cell)

    assert dispatch.run_calls == 0
    assert dispatch.close_calls == 1
    assert not dispatch.active
    assert not tuple(tmp_path.glob(".codex-eval-*"))
    assert not tuple(tmp_path.glob("runtime-quarantine/*.txt"))
