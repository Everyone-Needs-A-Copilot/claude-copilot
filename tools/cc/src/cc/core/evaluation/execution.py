"""Fail-closed production boundary for the preregistered evaluation matrix."""

from __future__ import annotations

import os
import re
import stat
import tempfile
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from cc.core.evaluation.identity import build_consumption_receipt
from cc.core.evaluation.matrix import EvaluationMatrix, MatrixCellPlan, build_matrix
from cc.core.evaluation.models import (
    ContentReceipt,
    EvaluationCell,
    LayerContentReceipt,
    LayerVariant,
    RuntimeName,
    RuntimeReceipt,
)
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256, packaged_cases_root

CLAUDE_EVALUATION_MODEL = "claude-fable-5"
CODEX_EVALUATION_MODEL = "gpt-5.6-sol"
_RUNTIME_MODELS = {
    RuntimeName.CLAUDE.value: CLAUDE_EVALUATION_MODEL,
    RuntimeName.CODEX.value: CODEX_EVALUATION_MODEL,
}
_EVALUATION_TASK_ID = 285
_PUBLISHER_SIGNER = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"


class EvaluationExecutionUnavailable(RuntimeError):
    """The canonical issuer could not authorize any runtime attempt."""

    def __init__(self, reason: str) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", reason):
            raise ValueError("Execution blocker must be a stable identifier.")
        self.reason = reason
        super().__init__(reason)


def _require_exact_matrix(fixtures_root: Path) -> EvaluationMatrix:
    try:
        selected = Path(fixtures_root)
        packaged = packaged_cases_root()
        if not selected.is_absolute() or not selected.samefile(packaged):
            raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
        matrix, _fixtures = build_matrix(selected)
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, EvaluationExecutionUnavailable):
            raise
        raise EvaluationExecutionUnavailable(
            "preregistered-matrix-unavailable"
        ) from exc
    if len(matrix.cells) != 28:
        raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
    return matrix


def _require_exact_models(runtime_models: Mapping[str, str]) -> None:
    if (
        not isinstance(runtime_models, Mapping)
        or dict(runtime_models) != _RUNTIME_MODELS
    ):
        raise EvaluationExecutionUnavailable("runtime-model-policy-invalid")


def _variant_tiers(variant: LayerVariant) -> tuple[str, ...]:
    return {
        LayerVariant.FOUNDATION: ("foundation",),
        LayerVariant.ORGANIZATION: ("foundation", "organization"),
        LayerVariant.DEPARTMENT: ("foundation", "organization", "department"),
        LayerVariant.PERSONAL: (
            "foundation",
            "organization",
            "department",
            "personal",
        ),
    }[variant]


def _codex_zero_call_content(plan: MatrixCellPlan) -> ContentReceipt:
    """Describe the exact fact that no Codex content or runtime was consumed."""

    policy = {
        "schema_version": "task285-codex-zero-call-v1",
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "case_id": plan.case_id,
        "variant": plan.variant.value,
        "runtime": RuntimeName.CODEX.value,
        "reason": "codex-live-runtime-unauthorized",
    }
    policy_sha256 = canonical_sha256(policy)
    layers = []
    for tier in _variant_tiers(plan.variant):
        for product in ("codex-copilot", "knowledge"):
            absence = canonical_sha256(
                {
                    **policy,
                    "tier": tier,
                    "product": product,
                    "resolution_action": "authenticated-absence",
                }
            )
            layers.append(
                LayerContentReceipt(
                    product=product,
                    tier=tier,
                    source_layer_identifier=f"{product}-{tier}-zero-call",
                    source_runtime=RuntimeName.CODEX.value,
                    source_adapter_version="zero-call-disposition-v1",
                    repository_identifier="cc/evaluation-runtime",
                    immutable_ref=f"sha256:{absence}",
                    tree_sha256=absence,
                    signer_identity=_PUBLISHER_SIGNER,
                    policy_sha256=policy_sha256,
                    manifest_sha256=PACKAGED_MATRIX_SHA256,
                    lock_sha256=policy_sha256,
                    contribution_ids=(),
                    content_digests=(),
                    resolution_action="authenticated-absence",
                    materialized_destinations=(),
                    source_tree=absence,
                )
            )
    ordered = tuple(
        sorted(
            layers,
            key=lambda item: (
                _variant_tiers(plan.variant).index(item.tier),
                item.product,
                item.repository_identifier,
            ),
        )
    )
    return ContentReceipt(
        variant=plan.variant,
        entitlement_receipt_sha256=policy_sha256,
        layers=ordered,
        composed_content_sha256=canonical_sha256({**policy, "content": "not-consumed"}),
        materialization_sha256=canonical_sha256({**policy, "materialization": "none"}),
    )


def _codex_zero_call_runtime_receipt() -> RuntimeReceipt:
    from cc.core.evaluation.live_runtime import (
        CODEX_ADAPTER_NAME,
        CODEX_ADAPTER_VERSION,
        _codex_native_executable,
        _executable_sha256,
    )
    from cc.core.executables import resolve_executable

    try:
        resolved = resolve_executable(RuntimeName.CODEX.value)
        if resolved is None:
            raise ValueError("Codex runtime is unavailable.")
        executable = _codex_native_executable(Path(resolved))
        executable_sha256 = _executable_sha256(executable)
    except (OSError, TypeError, ValueError) as exc:
        raise EvaluationExecutionUnavailable("codex-runtime-unavailable") from exc
    return RuntimeReceipt(
        runtime=RuntimeName.CODEX,
        executable_sha256=executable_sha256,
        runtime_version=None,
        model_version=CODEX_EVALUATION_MODEL,
        tool_availability=(),
        adapter_name=CODEX_ADAPTER_NAME,
        adapter_version=CODEX_ADAPTER_VERSION,
        capability_flags=(
            "live-runtime-unauthorized",
            "measurement-only",
            "zero-call",
        ),
    )


def _issue_codex_zero_call_cell(
    plan: MatrixCellPlan,
    loaded_fixture: object,
) -> EvaluationCell:
    """Issue one deterministic unsupported cell without routing or dispatch."""

    from cc.core.evaluation.attempt_policy import ATTEMPT_POLICY_SHA256
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
    from cc.core.evaluation.matrix import prompt_evidence_identity

    if (
        not isinstance(loaded_fixture, LoadedFixture)
        or not verify_loaded_fixture(loaded_fixture)
        or plan.runtime is not RuntimeName.CODEX
        or loaded_fixture.fixture.case_id != plan.case_id
        or loaded_fixture.fixture.revision != plan.revision
    ):
        raise EvaluationExecutionUnavailable("codex-zero-call-plan-invalid")
    runtime = _codex_zero_call_runtime_receipt()
    content = _codex_zero_call_content(plan)
    prompt_sha256 = prompt_evidence_identity(loaded_fixture)
    zero_call_journey = {
        "schema_version": "task285-zero-call-journey-v1",
        "task_id": _EVALUATION_TASK_ID,
        "matrix_sha256": PACKAGED_MATRIX_SHA256,
        "case_id": plan.case_id,
        "variant": plan.variant.value,
        "runtime": RuntimeName.CODEX.value,
        "route_contract_sha256": plan.route_contract_sha256,
        "state": "not-dispatched",
        "reason": "codex-live-runtime-unauthorized",
    }
    journey_sha256 = canonical_sha256(zero_call_journey)
    continuity_sha256 = canonical_sha256(
        {**zero_call_journey, "continuity": "not-started"}
    )
    consumption = build_consumption_receipt(
        task_id=_EVALUATION_TASK_ID,
        runtime_receipt=runtime,
        content_receipt=content,
        prompt_evidence_sha256=prompt_sha256,
        journey_evidence_sha256=journey_sha256,
        route_evidence_sha256=plan.route_contract_sha256,
        continuity_evidence_sha256=continuity_sha256,
    )
    runtime_configuration_sha256 = canonical_sha256(
        {**zero_call_journey, "runtime_receipt": runtime.executable_sha256}
    )
    command_policy_sha256 = canonical_sha256(
        {**zero_call_journey, "command": "not-issued"}
    )
    return EvaluationCell(
        case_id=plan.case_id,
        revision=plan.revision,
        fixture_sha256=loaded_fixture.fixture_sha256,
        prompt_evidence_sha256=prompt_sha256,
        variant=plan.variant,
        runtime_receipt=runtime,
        content_receipt=content,
        consumption_receipt=consumption,
        attempt=1,
        attempt_policy_sha256=ATTEMPT_POLICY_SHA256,
        runtime_configuration_sha256=runtime_configuration_sha256,
        tool_configuration_sha256=canonical_sha256(
            {**zero_call_journey, "tools": "not-advertised"}
        ),
        effective_full_prompt_sha256=canonical_sha256(
            {**zero_call_journey, "prompt": "not-created"}
        ),
        command_policy_sha256=command_policy_sha256,
    )


def _verify_codex_zero_call_cell(
    cell: EvaluationCell,
    loaded_fixture: object,
) -> bool:
    """Reissue the exact zero-call cell so copies cannot change its claims."""

    try:
        matrix, fixtures = build_matrix(packaged_cases_root())
        fixture = next(
            item
            for item in fixtures
            if item.fixture.case_id == getattr(loaded_fixture, "fixture").case_id
        )
        plan = next(
            item
            for item in matrix.cells
            if item.case_id == cell.case_id
            and item.variant is cell.variant
            and item.runtime is RuntimeName.CODEX
        )
        return bool(
            fixture.fixture_sha256 == loaded_fixture.fixture_sha256
            and fixture.fixture == loaded_fixture.fixture
            and cell == _issue_codex_zero_call_cell(plan, loaded_fixture)
        )
    except (AttributeError, OSError, StopIteration, TypeError, ValueError):
        return False


class _NoCallRuntime:
    """Tripwire proving an unsupported disposition never invokes a runtime."""

    def __init__(self) -> None:
        self.live_calls = 0

    def execute(self, _cell: EvaluationCell) -> object:
        self.live_calls += 1
        raise AssertionError("A zero-call disposition cannot execute a runtime.")


def _execute_codex_zero_call_matrix(
    matrix: EvaluationMatrix,
    loaded_fixtures: Sequence[object],
    artifact_root: Path,
) -> Mapping[str, object]:
    """Persist and fresh-reload all 14 exact Codex UNSUPPORTED cells."""

    from cc.core.evaluation.artifact import (
        close_artifact_receipt,
        load_durable_unsupported_run,
        verify_artifact_receipt,
        write_run_record,
    )
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
    from cc.core.evaluation.models import RunState
    from cc.core.evaluation.runner import EvaluationRunner

    if matrix.matrix_sha256 != PACKAGED_MATRIX_SHA256:
        raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
    fixtures = {
        item.fixture.case_id: item
        for item in loaded_fixtures
        if isinstance(item, LoadedFixture) and verify_loaded_fixture(item)
    }
    if len(fixtures) != 7:
        raise EvaluationExecutionUnavailable("preregistered-fixtures-unavailable")
    try:
        artifact_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        artifact_root.chmod(0o700)
    except OSError as exc:
        raise EvaluationExecutionUnavailable("artifact-root-unavailable") from exc
    _require_private_artifact_location(artifact_root)

    runtime = _NoCallRuntime()
    run_sha256s: list[str] = []
    plans = tuple(item for item in matrix.cells if item.runtime is RuntimeName.CODEX)
    if len(plans) != 14:
        raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
    for plan in plans:
        loaded = fixtures.get(plan.case_id)
        if loaded is None:
            raise EvaluationExecutionUnavailable("preregistered-fixtures-unavailable")
        cell = _issue_codex_zero_call_cell(plan, loaded)
        record = EvaluationRunner(runtime, loaded_fixture=loaded).run(cell)
        if record.state is not RunState.UNSUPPORTED:
            raise EvaluationExecutionUnavailable("codex-zero-call-disposition-invalid")
        receipt = write_run_record(
            artifact_root,
            record,
            cell=cell,
            loaded_fixture=loaded,
        )
        loaded_record = None
        try:
            if not verify_artifact_receipt(receipt):
                raise EvaluationExecutionUnavailable("codex-zero-call-evidence-invalid")
            loaded_record = load_durable_unsupported_run(
                artifact_root,
                record.run_sha256,
                cell=cell,
                loaded_fixture=loaded,
            )
            if loaded_record is None or not loaded_record.validate():
                raise EvaluationExecutionUnavailable("codex-zero-call-evidence-invalid")
            run_sha256s.append(loaded_record.record.run_sha256)
        finally:
            if loaded_record is not None:
                loaded_record.close()
            close_artifact_receipt(receipt)
    if runtime.live_calls != 0 or len(set(run_sha256s)) != 14:
        raise EvaluationExecutionUnavailable("codex-zero-call-disposition-invalid")
    document: dict[str, object] = {
        "schema_version": "task285-codex-unsupported-v1",
        "matrix_sha256": matrix.matrix_sha256,
        "runtime": RuntimeName.CODEX.value,
        "state": "unsupported",
        "reason": "codex-no-tool-isolation-unavailable",
        "live_calls_started": 0,
        "run_sha256s": run_sha256s,
    }
    document["evidence_sha256"] = canonical_sha256(document)
    return document


_PREPARED_CLAUDE_AUTHORITY = object()
_ISSUED_PREPARED_CLAUDE: weakref.WeakValueDictionary[int, "_PreparedClaudeCell"] = (
    weakref.WeakValueDictionary()
)


class _RetainedArtifactRoot:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.fd = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_DIRECTORY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(self.fd)
        self.identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_uid,
            stat.S_IMODE(metadata.st_mode),
        )
        self.validate()

    def validate(self) -> None:
        if self.fd < 0 or Path(os.path.realpath(self.path)) != self.path:
            raise ValueError("Prepared artifact root identity changed.")
        opened = os.fstat(self.fd)
        named = os.stat(self.path, follow_symlinks=False)
        for value in (opened, named):
            if (
                not stat.S_ISDIR(value.st_mode)
                or value.st_uid != os.geteuid()
                or stat.S_IMODE(value.st_mode) != 0o700
            ):
                raise ValueError("Prepared artifact root identity changed.")
        current = (
            opened.st_dev,
            opened.st_ino,
            opened.st_uid,
            stat.S_IMODE(opened.st_mode),
        )
        named_identity = (
            named.st_dev,
            named.st_ino,
            named.st_uid,
            stat.S_IMODE(named.st_mode),
        )
        if current != self.identity or named_identity != self.identity:
            raise ValueError("Prepared artifact root identity changed.")

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


@dataclass(frozen=True)
class _PreparedClaudeCell:
    """Non-authoritative holder for one exact, dispatch-bound Claude cell."""

    cell: EvaluationCell
    adapter: object
    content_projection: object
    journey_run_id: str
    ledger: object
    _loaded_fixture: object
    _artifact_root: Path
    _root_capability: _RetainedArtifactRoot
    _subject_sha256: str
    _seal: object
    _authority: object
    _personal_temporary: tempfile.TemporaryDirectory[str] | None = None
    _started: bool = False

    def __post_init__(self) -> None:
        if self._authority is not _PREPARED_CLAUDE_AUTHORITY:
            raise ValueError("Prepared Claude cell is not verifier-issued.")

    def _subject(self) -> str:
        from cc.core.evaluation.matrix import (
            fixture_packet_identity,
            route_contract_document,
        )

        return canonical_sha256(
            {
                "schema_version": "task285-prepared-claude-cell-v1",
                "matrix_sha256": PACKAGED_MATRIX_SHA256,
                "case_id": self.cell.case_id,
                "revision": self.cell.revision,
                "variant": self.cell.variant.value,
                "fixture_packet_sha256": fixture_packet_identity(self._loaded_fixture),
                "route_contract_sha256": route_contract_document(self.cell.case_id)[
                    "route_contract_sha256"
                ],
                "journey_run_id": self.journey_run_id,
                "ledger_task_id": getattr(self.ledger, "task_id", None),
                "ledger_instance": id(self.ledger),
                "artifact_root_identity": list(self._root_capability.identity),
            }
        )

    def begin_execution(self, loaded_fixture: object, artifact_root: Path) -> None:
        from cc.core.evaluation.fixtures import verify_loaded_fixture

        try:
            if (
                _ISSUED_PREPARED_CLAUDE.get(id(self)) is not self
                or self._started
                or loaded_fixture is not self._loaded_fixture
                or not verify_loaded_fixture(loaded_fixture)
                or artifact_root != self._artifact_root
                or Path(os.path.realpath(artifact_root)) != artifact_root
                or getattr(self.adapter, "_artifact_root", None) != self._artifact_root
                or self._subject_sha256 != self._subject()
            ):
                raise ValueError("Prepared Claude attempt identity changed.")
            self._root_capability.validate()
            self.adapter._require_cell(self.cell)
        except (OSError, TypeError, ValueError) as exc:
            raise EvaluationExecutionUnavailable(
                "claude-prepared-attempt-invalid"
            ) from exc
        object.__setattr__(self, "_started", True)

    def validate_in_use(self) -> None:
        try:
            if (
                _ISSUED_PREPARED_CLAUDE.get(id(self)) is not self
                or not self._started
                or self._subject_sha256 != self._subject()
            ):
                raise ValueError("Prepared Claude attempt identity changed.")
            self._root_capability.validate()
            self.adapter._require_cell(self.cell)
        except (OSError, TypeError, ValueError) as exc:
            raise EvaluationExecutionUnavailable(
                "claude-prepared-attempt-changed"
            ) from exc

    def close(self) -> None:
        if _ISSUED_PREPARED_CLAUDE.get(id(self)) is not self:
            return
        _ISSUED_PREPARED_CLAUDE.pop(id(self), None)
        close = getattr(self.content_projection, "close", None)
        try:
            if callable(close):
                close()
        finally:
            try:
                self._root_capability.close()
            finally:
                if self._personal_temporary is not None:
                    self._personal_temporary.cleanup()


def _prepare_claude_cell(
    plan: MatrixCellPlan,
    loaded_fixture: object,
    artifact_root: Path,
    ledger: object,
) -> _PreparedClaudeCell:
    """Resolve, bind, and authorize one exact Claude runtime attempt."""

    import secrets

    from cc.core.evaluation._authority import _verified_journey_identities
    from cc.core.evaluation.attempt_policy import ATTEMPT_POLICY_SHA256
    from cc.core.evaluation.content_authority import (
        issue_canonical_claude_content,
        verify_canonical_content_projection,
    )
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
    from cc.core.evaluation.journey_runtime import (
        TcJourneyLedger,
        begin_run,
        bind_prompt,
        prepare_run,
        resolve_specialist_knowledge,
        verify_dispatch,
    )
    from cc.core.evaluation.live_runtime import ClaudeNonInteractiveAdapter
    from cc.core.evaluation.matrix import (
        build_runtime_prompt,
        prompt_evidence_identity,
        runtime_configuration_identity,
    )
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
    )

    if (
        plan.runtime is not RuntimeName.CLAUDE
        or not isinstance(loaded_fixture, LoadedFixture)
        or not verify_loaded_fixture(loaded_fixture)
        or loaded_fixture.fixture.case_id != plan.case_id
        or loaded_fixture.fixture.revision != plan.revision
        or not isinstance(ledger, TcJourneyLedger)
    ):
        raise EvaluationExecutionUnavailable("claude-cell-plan-invalid")
    _require_private_artifact_location(artifact_root)
    prompt_sha256 = prompt_evidence_identity(loaded_fixture)
    session_id = f"task285-{plan.case_id}-{secrets.token_hex(12)}"
    personal_temporary = None
    personal_receipt = None
    projection = None
    root_capability = None
    transferred = False
    try:
        started = begin_run(
            task_id=_EVALUATION_TASK_ID,
            runtime=RuntimeName.CLAUDE.value,
            classification=plan.route_classification,
            specialists=(plan.expected_specialist,),
            events=(
                {
                    "kind": "transition",
                    "specialist": plan.expected_specialist,
                    "reason": "protocol-supplied",
                },
            ),
            prompt_sha256=prompt_sha256,
            session_id=session_id,
            ledger=ledger,
        )
        prepared = prepare_run(
            str(started["run_id"]),
            plan.expected_specialist,
            variant=plan.variant.value,
            ledger=ledger,
            resolver=resolve_specialist_knowledge,
        )
        if plan.variant is LayerVariant.PERSONAL:
            personal_temporary = tempfile.TemporaryDirectory(
                prefix=".cc-evaluation-personal-attempt-"
            )
            personal_root = Path(personal_temporary.name)
            personal_root.chmod(0o700)
            personal_receipt = materialize_personal_snapshot(
                personal_root / "personal-content"
            )
        projection = issue_canonical_claude_content(
            variant=plan.variant,
            specialist=plan.expected_specialist,
            case_id=plan.case_id,
            personal_snapshot_receipt=personal_receipt,
        )
        if (
            not verify_canonical_content_projection(projection)
            or projection.knowledge_payload != prepared.knowledge_payload
            or tuple(dict(item) for item in projection.knowledge_sources)
            != tuple(dict(item) for item in prepared.sources)
        ):
            raise EvaluationExecutionUnavailable("claude-content-route-mismatch")
        packet = build_runtime_prompt(
            loaded_fixture,
            variant=plan.variant,
            runtime=RuntimeName.CLAUDE,
            prepared=prepared,
        )
        if packet.route_contract_sha256 != plan.route_contract_sha256:
            raise EvaluationExecutionUnavailable("claude-route-contract-mismatch")
        bind_prompt(
            prepared.run_id,
            prepared.specialist,
            packet.full_prompt_sha256,
            ledger=ledger,
        )

        def agent_resolver(requested_variant: object, requested_specialist: str):
            if (
                requested_variant is not plan.variant
                or requested_specialist != plan.expected_specialist
            ):
                raise ValueError("Runtime specialist projection changed.")
            return projection.runtime_projection

        adapter = ClaudeNonInteractiveAdapter(
            packet,
            artifact_root=artifact_root,
            model=CLAUDE_EVALUATION_MODEL,
            agent_resolver=agent_resolver,
        )
        dispatch = verify_dispatch(
            session_id=session_id,
            specialist=prepared.specialist,
            marker=prepared.invocation_marker,
            prompt_sha256=packet.full_prompt_sha256,
            knowledge_sha256=prepared.composed_content_sha256,
            ledger_factory=lambda _task_id: ledger,
            resolver=resolve_specialist_knowledge,
        )
        if dispatch.get("state") != "dispatch_authorized":
            raise EvaluationExecutionUnavailable("claude-dispatch-unavailable")
        journey = _verified_journey_identities(prepared.run_id, ledger)
        if journey is None:
            raise EvaluationExecutionUnavailable("claude-journey-evidence-invalid")
        consumption = build_consumption_receipt(
            task_id=_EVALUATION_TASK_ID,
            runtime_receipt=adapter.runtime_receipt,
            content_receipt=projection.content_receipt,
            prompt_evidence_sha256=prompt_sha256,
            journey_evidence_sha256=str(journey["journey_evidence_sha256"]),
            route_evidence_sha256=str(journey["route_evidence_sha256"]),
            continuity_evidence_sha256=str(journey["continuity_evidence_sha256"]),
        )
        cell = EvaluationCell(
            case_id=plan.case_id,
            revision=plan.revision,
            fixture_sha256=loaded_fixture.fixture_sha256,
            prompt_evidence_sha256=prompt_sha256,
            variant=plan.variant,
            runtime_receipt=adapter.runtime_receipt,
            content_receipt=projection.content_receipt,
            consumption_receipt=consumption,
            attempt=1,
            attempt_policy_sha256=ATTEMPT_POLICY_SHA256,
            runtime_configuration_sha256=runtime_configuration_identity(packet),
            tool_configuration_sha256=adapter.tool_configuration_sha256,
            effective_full_prompt_sha256=adapter.effective_full_prompt_sha256,
            command_policy_sha256=adapter.command_policy_sha256,
        )
        adapter._require_cell(cell)
        root_capability = _RetainedArtifactRoot(artifact_root)
        seal = object()
        result = _PreparedClaudeCell(
            cell,
            adapter,
            projection,
            prepared.run_id,
            ledger,
            loaded_fixture,
            artifact_root,
            root_capability,
            "0" * 64,
            seal,
            _PREPARED_CLAUDE_AUTHORITY,
            personal_temporary,
        )
        object.__setattr__(result, "_subject_sha256", result._subject())
        _ISSUED_PREPARED_CLAUDE[id(result)] = result
        transferred = True
        return result
    except EvaluationExecutionUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise EvaluationExecutionUnavailable("claude-cell-preparation-failed") from exc
    finally:
        if not transferred:
            if root_capability is not None:
                root_capability.close()
            close = getattr(projection, "close", None)
            if callable(close):
                close()
            elif personal_receipt is not None:
                personal_receipt.close()
            if personal_temporary is not None:
                personal_temporary.cleanup()


def _execute_prepared_claude_cell(
    prepared: _PreparedClaudeCell,
    loaded_fixture: object,
    artifact_root: Path,
) -> Mapping[str, object]:
    """Execute, persist, and fresh-reload one already authorized Claude cell."""

    from cc.core.evaluation.artifact import (
        close_artifact_receipt,
        load_durable_completed_run,
        verify_artifact_receipt,
        write_run_record,
    )
    from cc.core.evaluation.live_runtime import close_authenticated_runtime_output
    from cc.core.evaluation.models import RunState
    from cc.core.evaluation.runner import EvaluationRunner

    prepared.begin_execution(loaded_fixture, artifact_root)
    receipt = None
    loaded = None
    output = None
    try:
        runner = EvaluationRunner(
            prepared.adapter,
            loaded_fixture=loaded_fixture,
            journey_run_id=prepared.journey_run_id,
            journey_ledger=prepared.ledger,
            artifact_root=artifact_root,
            content_projection=prepared.content_projection,
        )
        record = runner.run(prepared.cell)
        prepared.validate_in_use()
        output = runner.completion_output(record)
        if record.state is RunState.COMPLETED and output is None:
            raise EvaluationExecutionUnavailable("claude-completion-evidence-missing")
        receipt = write_run_record(
            artifact_root,
            record,
            cell=prepared.cell,
            loaded_fixture=loaded_fixture,
            journey_run_id=prepared.journey_run_id,
            journey_ledger=prepared.ledger,
            authenticated_output=output,
        )
        if not verify_artifact_receipt(receipt):
            raise EvaluationExecutionUnavailable("claude-run-evidence-invalid")
        if record.state is not RunState.COMPLETED:
            raise EvaluationExecutionUnavailable(f"claude-attempt-{record.state.value}")
        loaded = load_durable_completed_run(
            artifact_root,
            record.run_sha256,
            cell=prepared.cell,
            loaded_fixture=loaded_fixture,
            journey_run_id=prepared.journey_run_id,
            journey_ledger=prepared.ledger,
        )
        if loaded is None or not loaded.validate():
            raise EvaluationExecutionUnavailable("claude-run-evidence-invalid")
        prepared.validate_in_use()
        document: dict[str, object] = {
            "schema_version": "task285-claude-completed-v1",
            "case_id": prepared.cell.case_id,
            "variant": prepared.cell.variant.value,
            "runtime": RuntimeName.CLAUDE.value,
            "state": RunState.COMPLETED.value,
            "run_sha256": loaded.record.run_sha256,
            "journey_run_id_sha256": canonical_sha256(
                {"journey_run_id": prepared.journey_run_id}
            ),
            "live_calls_started": 1,
        }
        document["evidence_sha256"] = canonical_sha256(document)
        return document
    except EvaluationExecutionUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise EvaluationExecutionUnavailable("claude-attempt-evidence-failed") from exc
    finally:
        if loaded is not None:
            loaded.close()
        if receipt is not None:
            close_artifact_receipt(receipt)
        if output is not None:
            close_authenticated_runtime_output(output)
        prepared.close()


@dataclass(frozen=True)
class _ClaudeTerminalSubject:
    cell: EvaluationCell
    loaded_fixture: object
    journey_run_id: str
    journey_ledger: object
    run_sha256: str


def _phase_one_report_document(
    matrix: EvaluationMatrix,
    assessment: object,
    runs: tuple[object, ...],
    *,
    live_calls_started: int,
) -> dict[str, object]:
    from cc.core.evaluation.artifact import LoadedDurableRunEvidence
    from cc.core.evaluation.assessment import (
        LoadedDurableAssessmentManifestEvidence,
    )
    from cc.core.evaluation.models import RunState
    from cc.core.evaluation.portfolio import _matrix_is_authentic

    if (
        not _matrix_is_authentic(matrix)
        or not isinstance(assessment, LoadedDurableAssessmentManifestEvidence)
        or not assessment.validate()
        or len(runs) != 28
        or live_calls_started != 14
        or any(
            not isinstance(item, LoadedDurableRunEvidence) or not item.validate()
            for item in runs
        )
    ):
        raise EvaluationExecutionUnavailable("phase-one-evidence-invalid")
    by_key = {
        (
            item.record.case_id,
            item.record.variant,
            item.record.runtime,
        ): item
        for item in runs
    }
    ordered = []
    for plan in matrix.cells:
        item = by_key.get((plan.case_id, plan.variant, plan.runtime))
        expected_state = (
            RunState.COMPLETED
            if plan.runtime is RuntimeName.CLAUDE
            else RunState.UNSUPPORTED
        )
        if item is None or item.record.state is not expected_state:
            raise EvaluationExecutionUnavailable("phase-one-terminal-coverage-invalid")
        ordered.append(item.record.run_sha256)
    if len(set(ordered)) != 28:
        raise EvaluationExecutionUnavailable("phase-one-terminal-coverage-invalid")
    identity: dict[str, object] = {
        "schema_version": "task285-phase-one-execution-v1",
        "matrix_sha256": matrix.matrix_sha256,
        "state": "awaiting-assessment",
        "acceptance_state": "not-evaluated",
        "initial_cells_started": 28,
        "total_attempts_started": 28,
        "live_calls_started": live_calls_started,
        "completed_cells": 14,
        "unsupported_cells": 14,
        "assessment_manifest_sha256": assessment.manifest_artifact_sha256,
        "assessment_bundle_sha256": assessment.bundle_artifact_sha256,
        "terminal_run_sha256": ordered,
        "blockers": [],
    }
    return {**identity, "execution_sha256": canonical_sha256(identity)}


def _persist_phase_one_handoff(
    matrix: EvaluationMatrix,
    fixtures: tuple[object, ...],
    runs: tuple[object, ...],
    artifact_root: Path,
    *,
    live_calls_started: int,
) -> Mapping[str, object]:
    from cc.core.evaluation.assessment import persist_assessment_manifest
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture

    exact_fixtures = tuple(
        item
        for item in fixtures
        if isinstance(item, LoadedFixture) and verify_loaded_fixture(item)
    )
    if len(exact_fixtures) != 7 or len(exact_fixtures) != len(fixtures):
        raise EvaluationExecutionUnavailable("preregistered-fixtures-unavailable")
    assessment = None
    try:
        assessment = persist_assessment_manifest(
            artifact_root,
            matrix,
            fixtures=exact_fixtures,
            runs=runs,
        )
        return _phase_one_report_document(
            matrix,
            assessment,
            runs,
            live_calls_started=live_calls_started,
        )
    except EvaluationExecutionUnavailable:
        raise
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise EvaluationExecutionUnavailable("phase-one-handoff-failed") from exc
    finally:
        if assessment is not None:
            assessment.close()


def _execute_phase_one_matrix(
    matrix: EvaluationMatrix,
    loaded_fixtures: Sequence[object],
    artifact_root: Path,
    *,
    ledger_factory: Callable[[MatrixCellPlan], object] | None = None,
) -> Mapping[str, object]:
    """Run 14 Claude cells, preserve 14 Codex UNSUPPORTED cells, then hand off."""

    from cc.core.evaluation.artifact import (
        load_durable_completed_run,
        load_durable_unsupported_run,
    )
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
    from cc.core.evaluation.journey_runtime import TcJourneyLedger
    from cc.core.evaluation.portfolio import _matrix_is_authentic

    if not _matrix_is_authentic(matrix):
        raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
    fixtures = {
        item.fixture.case_id: item
        for item in loaded_fixtures
        if isinstance(item, LoadedFixture) and verify_loaded_fixture(item)
    }
    if len(loaded_fixtures) != 7 or len(fixtures) != 7:
        raise EvaluationExecutionUnavailable("preregistered-fixtures-unavailable")
    try:
        artifact_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        artifact_root.chmod(0o700)
    except OSError as exc:
        raise EvaluationExecutionUnavailable("artifact-root-unavailable") from exc
    _require_private_artifact_location(artifact_root)

    def default_ledger_factory(_plan: MatrixCellPlan) -> object:
        return TcJourneyLedger(_EVALUATION_TASK_ID)

    selected_ledger_factory = ledger_factory or default_ledger_factory

    claude_subjects: list[_ClaudeTerminalSubject] = []
    loaded_runs = []
    try:
        claude_plans = tuple(
            item for item in matrix.cells if item.runtime is RuntimeName.CLAUDE
        )
        if len(claude_plans) != 14:
            raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
        for plan in claude_plans:
            loaded_fixture = fixtures[plan.case_id]
            ledger = selected_ledger_factory(plan)
            prepared = _prepare_claude_cell(
                plan,
                loaded_fixture,
                artifact_root,
                ledger,
            )
            cell = prepared.cell
            journey_run_id = prepared.journey_run_id
            try:
                document = _execute_prepared_claude_cell(
                    prepared,
                    loaded_fixture,
                    artifact_root,
                )
            except BaseException:
                prepared.close()
                raise
            run_sha256 = str(document.get("run_sha256", ""))
            if (
                document.get("state") != "completed"
                or document.get("live_calls_started") != 1
                or not re.fullmatch(r"[0-9a-f]{64}", run_sha256)
            ):
                raise EvaluationExecutionUnavailable("claude-run-evidence-invalid")
            claude_subjects.append(
                _ClaudeTerminalSubject(
                    cell,
                    loaded_fixture,
                    journey_run_id,
                    ledger,
                    run_sha256,
                )
            )

        codex_document = _execute_codex_zero_call_matrix(
            matrix,
            tuple(fixtures.values()),
            artifact_root,
        )
        if (
            codex_document.get("live_calls_started") != 0
            or codex_document.get("state") != "unsupported"
        ):
            raise EvaluationExecutionUnavailable("codex-zero-call-evidence-invalid")

        by_key = {}
        for subject in claude_subjects:
            loaded = load_durable_completed_run(
                artifact_root,
                subject.run_sha256,
                cell=subject.cell,
                loaded_fixture=subject.loaded_fixture,
                journey_run_id=subject.journey_run_id,
                journey_ledger=subject.journey_ledger,
            )
            if loaded is None or not loaded.validate():
                raise EvaluationExecutionUnavailable("claude-run-evidence-invalid")
            loaded_runs.append(loaded)
            by_key[
                (
                    subject.cell.case_id,
                    subject.cell.variant,
                    RuntimeName.CLAUDE,
                )
            ] = loaded
        codex_plans = tuple(
            item for item in matrix.cells if item.runtime is RuntimeName.CODEX
        )
        run_sha256s = codex_document.get("run_sha256s")
        if not isinstance(run_sha256s, list) or len(run_sha256s) != len(codex_plans):
            raise EvaluationExecutionUnavailable("codex-zero-call-evidence-invalid")
        for plan, run_sha256 in zip(codex_plans, run_sha256s, strict=True):
            loaded_fixture = fixtures[plan.case_id]
            cell = _issue_codex_zero_call_cell(plan, loaded_fixture)
            loaded = load_durable_unsupported_run(
                artifact_root,
                str(run_sha256),
                cell=cell,
                loaded_fixture=loaded_fixture,
            )
            if loaded is None or not loaded.validate():
                raise EvaluationExecutionUnavailable("codex-zero-call-evidence-invalid")
            loaded_runs.append(loaded)
            by_key[(plan.case_id, plan.variant, RuntimeName.CODEX)] = loaded
        ordered_runs = tuple(
            by_key[(plan.case_id, plan.variant, plan.runtime)] for plan in matrix.cells
        )
        return _persist_phase_one_handoff(
            matrix,
            tuple(loaded_fixtures),
            ordered_runs,
            artifact_root,
            live_calls_started=14,
        )
    except EvaluationExecutionUnavailable:
        raise
    except (
        KeyError,
        OSError,
        RuntimeError,
        StopIteration,
        TypeError,
        ValueError,
    ) as exc:
        raise EvaluationExecutionUnavailable("phase-one-execution-failed") from exc
    finally:
        for item in loaded_runs:
            item.close()


def _require_private_artifact_location(artifact_root: Path) -> None:
    if not isinstance(artifact_root, Path) or not artifact_root.is_absolute():
        raise EvaluationExecutionUnavailable("artifact-root-policy-invalid")
    try:
        if Path(os.path.realpath(artifact_root)) != artifact_root:
            raise EvaluationExecutionUnavailable("artifact-root-policy-invalid")
        if artifact_root.exists() or artifact_root.is_symlink():
            metadata = artifact_root.lstat()
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o700
                or metadata.st_uid != os.getuid()
            ):
                raise EvaluationExecutionUnavailable("artifact-root-policy-invalid")
            return
        parent = artifact_root.parent
        metadata = parent.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o022
        ):
            raise EvaluationExecutionUnavailable("artifact-root-policy-invalid")
    except OSError as exc:
        raise EvaluationExecutionUnavailable("artifact-root-policy-invalid") from exc


def _verify_canonical_claude_content(matrix: EvaluationMatrix) -> None:
    """Revalidate every distinct Claude source projection without dispatching."""

    from cc.core.evaluation.content_authority import (
        CanonicalContentUnavailable,
        issue_canonical_claude_content,
        verify_canonical_content_projection,
    )
    from cc.evaluation_fixtures.personal_snapshot import (
        materialize_personal_snapshot,
    )

    plans = tuple(item for item in matrix.cells if item.runtime is RuntimeName.CLAUDE)
    seen: set[tuple[str, LayerVariant, str]] = set()
    for plan in plans:
        key = (plan.case_id, plan.variant, plan.expected_specialist)
        if key in seen:
            continue
        seen.add(key)
        receipt = None
        temporary = None
        projection = None
        pending: BaseException | None = None
        try:
            if plan.variant is LayerVariant.PERSONAL:
                temporary = tempfile.TemporaryDirectory(
                    prefix=".cc-evaluation-personal-readiness-"
                )
                private_root = Path(temporary.name)
                private_root.chmod(0o700)
                receipt = materialize_personal_snapshot(
                    private_root / "personal-content"
                )
            projection = issue_canonical_claude_content(
                variant=plan.variant,
                specialist=plan.expected_specialist,
                case_id=plan.case_id,
                personal_snapshot_receipt=receipt,
            )
            if not verify_canonical_content_projection(projection):
                raise EvaluationExecutionUnavailable(
                    "canonical-content-identity-invalid"
                )
        except BaseException as exc:
            pending = exc
        cleanup_failure: BaseException | None = None
        for close in (
            getattr(projection, "close", None),
            getattr(receipt, "close", None),
        ):
            if not callable(close):
                continue
            try:
                close()
            except BaseException as exc:
                cleanup_failure = cleanup_failure or exc
        if temporary is not None:
            try:
                temporary.cleanup()
            except BaseException as exc:
                cleanup_failure = cleanup_failure or exc
        if cleanup_failure is not None:
            raise EvaluationExecutionUnavailable(
                "canonical-content-cleanup-failed"
            ) from (pending or cleanup_failure)
        if pending is None:
            continue
        if isinstance(pending, EvaluationExecutionUnavailable):
            raise pending
        if isinstance(pending, CanonicalContentUnavailable):
            raise EvaluationExecutionUnavailable(
                f"canonical-content-{pending.reason}"
            ) from pending
        if isinstance(pending, Exception):
            raise EvaluationExecutionUnavailable(
                "canonical-content-verifier-unavailable"
            ) from pending
        raise pending


def _verify_runtime_authentication() -> None:
    from cc.core.evaluation.live_runtime import runtime_authentication_status
    from cc.core.executables import resolve_executable

    for runtime in RuntimeName:
        try:
            resolved = resolve_executable(runtime.value)
        except (OSError, TypeError, ValueError) as exc:
            raise EvaluationExecutionUnavailable(
                f"{runtime.value}-runtime-unavailable"
            ) from exc
        if resolved is None:
            raise EvaluationExecutionUnavailable(f"{runtime.value}-runtime-unavailable")
        executable = Path(resolved)
        try:
            authenticated, reason = runtime_authentication_status(runtime, executable)
        except (OSError, TypeError, ValueError) as exc:
            raise EvaluationExecutionUnavailable(
                f"{runtime.value}-runtime-not-authenticated"
            ) from exc
        if not authenticated:
            stable_reason = (
                reason
                if isinstance(reason, str)
                and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", reason)
                else "runtime-not-authenticated"
            )
            raise EvaluationExecutionUnavailable(f"{runtime.value}-{stable_reason}")


def _require_canonical_readiness(matrix: EvaluationMatrix) -> None:
    _verify_canonical_claude_content(matrix)
    _verify_runtime_authentication()
    # The sealed 0.147 offline registry proof is a necessary but not yet
    # sufficient Codex execution capability. Production remains zero-call
    # until its reviewed receipt is wired to an exact additive source issuer.
    raise EvaluationExecutionUnavailable("codex-content-projection-unavailable")


def issue_matrix_execution(
    *,
    fixtures_root: Path,
    artifact_root: Path,
    runtime_models: Mapping[str, str],
) -> Mapping[str, object]:
    """Authorize only the exact packaged matrix and released runtime policy.

    Readiness consumes verifier-owned source and runtime facts directly. It
    never accepts caller-authored proof dictionaries, never creates an artifact
    directory before every prerequisite passes, and currently fails before any
    model call because the additive Codex content issuer is not yet available.
    """

    matrix = _require_exact_matrix(fixtures_root)
    _require_exact_models(runtime_models)
    _require_private_artifact_location(artifact_root)
    _require_canonical_readiness(matrix)
    _verified_matrix, fixtures = build_matrix(fixtures_root)
    if _verified_matrix != matrix:
        raise EvaluationExecutionUnavailable("preregistered-matrix-unavailable")
    return _execute_phase_one_matrix(
        matrix,
        fixtures,
        artifact_root,
    )


__all__ = [
    "CLAUDE_EVALUATION_MODEL",
    "CODEX_EVALUATION_MODEL",
    "EvaluationExecutionUnavailable",
    "issue_matrix_execution",
]
