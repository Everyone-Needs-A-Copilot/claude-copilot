"""Private authority boundary for evaluation evidence.

Nothing in this module is re-exported by ``cc.core.evaluation``. Production
issuance consumes the verified fixture loader and TASK-296 ledger inspection;
the adapter stays fail-closed until signed TASK-297 evidence exists.
"""

from __future__ import annotations

import weakref
from dataclasses import dataclass, field
from typing import Callable

from cc.core.evaluation.identity import (
    consumption_receipt_identity,
    content_receipt_identity,
    runtime_receipt_identity,
)
from cc.core.evaluation.models import (
    _EVIDENCE_AUTHORITY,
    EvaluationCell,
    GateObservation,
    GateState,
    PreflightGate,
    PreflightResult,
    RuntimeName,
)
from cc.core.evaluation.preflight import evaluate_preflight
from cc.core.evaluation.schema import canonical_sha256

_AUTHORITY_TOKEN = object()
_ISSUED_AUTHORITIES: weakref.WeakValueDictionary[int, "_EvaluationAuthority"] = (
    weakref.WeakValueDictionary()
)


def _verified_journey_identities(
    run_id: str, journey_ledger: object
) -> dict[str, object] | None:
    """Derive identities only from TASK-296's fully validated terminal ledger."""

    from cc.core.evaluation.journey_runtime import (
        TcJourneyLedger,
        _public_state,
        _state,
    )

    if not isinstance(journey_ledger, TcJourneyLedger):
        return None
    try:
        with journey_ledger.claim(run_id):
            state = _state(run_id, journey_ledger)
            projected = _public_state(run_id, state)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    if (
        len(state["final_authorization"]) != 1
        or projected.get("status") != "all_dispatches_authorized"
        or projected.get("evidence_claim") != "dispatch_observed_and_authorized_only"
        or projected.get("run_id") != run_id
    ):
        return None
    begin = state["begin_record"]
    final = state["final_authorization"][0]
    route_sha256 = canonical_sha256(begin["route"])
    continuity_sha256 = canonical_sha256(
        [
            {
                "generation": item["generation"],
                "capsule_sha256": item["capsule_sha256"],
            }
            for item in state["pause_capsule"]
        ]
    )
    invocation_sha256 = canonical_sha256(
        {
            "prepare": state["prepare"],
            "prompt_binding": state["prompt_binding"],
            "dispatch_authorization": state["dispatch_authorization"],
            "security_sha256": canonical_sha256(begin["security"]),
        }
    )
    terminal_sha256 = canonical_sha256(
        {
            "result_sha256": final["result_sha256"],
            "dispatch_authorizations_sha256": final["dispatch_authorizations_sha256"],
            "projected_result_sha256": canonical_sha256(projected),
        }
    )
    snapshot_sha256 = canonical_sha256(
        {
            "begin": begin,
            "prepare": state["prepare"],
            "prompt_binding": state["prompt_binding"],
            "dispatch_authorization": state["dispatch_authorization"],
            "pause_capsule": state["pause_capsule"],
            "final_authorization": state["final_authorization"],
        }
    )
    journey_sha256 = canonical_sha256(
        {
            "schema_version": "task296-evaluation-evidence-v1",
            "task_id": begin["task_id"],
            "run_id": run_id,
            "session_id_sha256": begin["session_id_sha256"],
            "prompt_sha256": begin["prompt_sha256"],
            "route_evidence_sha256": route_sha256,
            "continuity_evidence_sha256": continuity_sha256,
            "invocation_receipts_sha256": invocation_sha256,
            "terminal_evidence_sha256": terminal_sha256,
            "terminal_snapshot_sha256": snapshot_sha256,
        }
    )
    return {
        "task_id": begin["task_id"],
        "run_id": run_id,
        "session_id_sha256": begin["session_id_sha256"],
        "prompt_sha256": begin["prompt_sha256"],
        "route_evidence_sha256": route_sha256,
        "continuity_evidence_sha256": continuity_sha256,
        "invocation_receipts_sha256": invocation_sha256,
        "terminal_evidence_sha256": terminal_sha256,
        "terminal_snapshot_sha256": snapshot_sha256,
        "journey_evidence_sha256": journey_sha256,
        "runtime": (
            state["prepare"][0].get("runtime") if len(state["prepare"]) == 1 else None
        ),
        "variant": (
            state["prepare"][0].get("variant") if len(state["prepare"]) == 1 else None
        ),
        "specialist": (
            state["prepare"][0].get("specialist")
            if len(state["prepare"]) == 1
            else None
        ),
        "stage_index": (
            state["prepare"][0].get("stage_index")
            if len(state["prepare"]) == 1
            else None
        ),
        "composed_content_sha256": (
            state["prepare"][0].get("composed_content_sha256")
            if len(state["prepare"]) == 1
            else None
        ),
        "sources": (
            state["prepare"][0].get("sources") if len(state["prepare"]) == 1 else None
        ),
        "invocation_marker": (
            state["prepare"][0].get("invocation_marker")
            if len(state["prepare"]) == 1
            else None
        ),
        "bound_prompt_sha256": (
            state["prompt_binding"][0].get("prompt_sha256")
            if len(state["prompt_binding"]) == 1
            else None
        ),
    }


def _cell_subject(cell: EvaluationCell) -> str:
    return canonical_sha256(
        {
            "case_id": cell.case_id,
            "revision": cell.revision,
            "fixture_sha256": cell.fixture_sha256,
            "runtime_receipt_sha256": runtime_receipt_identity(cell.runtime_receipt),
            "content_receipt_sha256": content_receipt_identity(cell.content_receipt),
            "consumption_receipt_sha256": consumption_receipt_identity(
                cell.consumption_receipt
            ),
            "prompt_evidence_sha256": cell.prompt_evidence_sha256,
        }
    )


@dataclass(frozen=True)
class _EvaluationAuthority:
    subject_sha256: str
    preflight: PreflightResult
    _token: object
    _content_projection: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _cleanup: Callable[[], None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._token is not _AUTHORITY_TOKEN:
            raise ValueError("Evaluation authority is invalid.")

    def applies_to(self, cell: EvaluationCell) -> bool:
        if _ISSUED_AUTHORITIES.get(
            id(self)
        ) is not self or self.subject_sha256 != _cell_subject(cell):
            return False
        if self._content_projection is None:
            return True
        from cc.core.evaluation.content_authority import (
            verify_canonical_content_projection,
        )

        return verify_canonical_content_projection(self._content_projection)

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if _ISSUED_AUTHORITIES.get(id(self)) is not self:
            return
        _ISSUED_AUTHORITIES.pop(id(self), None)
        close = getattr(self._content_projection, "close", None)
        try:
            if callable(close):
                close()
        finally:
            if self._cleanup is not None:
                self._cleanup()

    def run_runtime(self, action):
        if self._content_projection is None:
            return action()
        return self._content_projection.run_authorized(action)


def _issue_evaluation_authority(
    subject_sha256: str,
    preflight: PreflightResult,
    *,
    content_projection: object | None = None,
    cleanup: Callable[[], None] | None = None,
) -> _EvaluationAuthority:
    authority = _EvaluationAuthority(
        subject_sha256,
        preflight,
        _AUTHORITY_TOKEN,
        content_projection,
        cleanup,
    )
    _ISSUED_AUTHORITIES[id(authority)] = authority
    return authority


def _observation(
    gate: PreflightGate,
    state: GateState,
    reason: str,
    actor: str,
    prerequisite: str,
) -> GateObservation:
    return GateObservation(
        gate,
        state,
        reason,
        actor,
        prerequisite,
        _EVIDENCE_AUTHORITY if state is GateState.PASS else None,
    )


def _claude_runtime_facts(
    cell: EvaluationCell,
    *,
    loaded_fixture: object,
    state: dict[str, object],
    projection: object,
    runtime_adapter: object | None,
) -> dict[PreflightGate, tuple[GateState, str, str, str]]:
    """Recompute every non-source Claude gate from exact production inputs."""

    import hashlib
    import tempfile
    from pathlib import Path

    from cc.core.evaluation.execution import CLAUDE_EVALUATION_MODEL
    from cc.core.evaluation.identity import prepared_sources_match_content_receipt
    from cc.core.evaluation.journey_runtime import (
        PreparedInvocation,
        resolve_specialist_knowledge,
    )
    from cc.core.evaluation.live_runtime import ClaudeNonInteractiveAdapter
    from cc.core.evaluation.matrix import build_runtime_prompt
    from cc.core.evaluation.safety import require_safe_synthetic_text

    specialist = str(state.get("specialist") or "")
    try:
        payload, sources = resolve_specialist_knowledge(
            specialist,
            cell.variant.value,
            RuntimeName.CLAUDE.value,
        )
        prepared = PreparedInvocation(
            run_id=str(state.get("run_id") or ""),
            specialist=specialist,
            variant=cell.variant.value,
            runtime=RuntimeName.CLAUDE.value,
            stage_index=0,
            invocation_marker=str(state.get("invocation_marker") or ""),
            knowledge_payload=payload,
            agent_prompt_fragment=(
                "CC-JOURNEY-INVOCATION: "
                + str(state.get("invocation_marker") or "")
                + "\nCC-JOURNEY-KNOWLEDGE-BEGIN\n"
                + payload
                + "\nCC-JOURNEY-KNOWLEDGE-END"
            ),
            composed_content_sha256=hashlib.sha256(payload.encode()).hexdigest(),
            sources=sources,
            prompt_sha256=str(state.get("bound_prompt_sha256") or ""),
        )
        packet = build_runtime_prompt(
            loaded_fixture,
            variant=cell.variant,
            runtime=RuntimeName.CLAUDE,
            prepared=prepared,
        )
        if (
            prepared.composed_content_sha256 != state.get("composed_content_sha256")
            or [dict(item) for item in prepared.sources] != state.get("sources")
            or packet.full_prompt_sha256 != state.get("bound_prompt_sha256")
            or not prepared_sources_match_content_receipt(
                projection.content_receipt,
                (*prepared.sources, projection.runtime_projection.source_receipt),
            )
        ):
            raise ValueError("Runtime content differs from the journey evidence.")

        def agent_resolver(requested_variant: object, requested_specialist: str):
            if (
                requested_variant is not cell.variant
                or requested_specialist != specialist
            ):
                raise ValueError("Runtime specialist projection changed.")
            return projection.runtime_projection

        temporary = None
        adapter = runtime_adapter
        if adapter is None:
            temporary = tempfile.TemporaryDirectory(
                prefix=".cc-evaluation-runtime-verifier-"
            )
            root = Path(temporary.name)
            root.chmod(0o700)
            adapter = ClaudeNonInteractiveAdapter(
                packet,
                artifact_root=root,
                model=CLAUDE_EVALUATION_MODEL,
                agent_resolver=agent_resolver,
            )
        try:
            if type(adapter) is not ClaudeNonInteractiveAdapter:
                raise ValueError("Runtime adapter type is not canonical.")
            adapter._require_cell(cell)
            if cell.runtime_receipt != adapter.runtime_receipt:
                raise ValueError("Runtime receipt differs from the adapter.")
            require_safe_synthetic_text(
                packet.user_prompt_text,
                location_class="runtime-input",
            )
        finally:
            if temporary is not None:
                temporary.cleanup()
    except (AttributeError, OSError, TypeError, ValueError):
        return {}

    return {
        PreflightGate.RESOLUTION_IDENTITY: (
            GateState.PASS,
            "exact-runtime-content",
            "content-verifier",
            "journey-bound-content",
        ),
        PreflightGate.RUNTIME_ADAPTER: (
            GateState.PASS,
            "claude-adapter-verified",
            "runtime-verifier",
            "exact-native-adapter",
        ),
        PreflightGate.REQUIRED_CONTENT: (
            GateState.PASS,
            "required-content-present",
            "content-verifier",
            "signed-specialist-content",
        ),
        PreflightGate.SAFETY_SCAN: (
            GateState.PASS,
            "synthetic-input-verified",
            "fixture-loader",
            "value-suppressing-scan",
        ),
        PreflightGate.PERSONAL_NON_LEAKAGE: (
            GateState.PASS,
            "private-oracle-excluded",
            "privacy-verifier",
            "oracle-runtime-separation",
        ),
        PreflightGate.NO_EXTERNAL_MUTATION: (
            GateState.PASS,
            "tools-and-mutation-disabled",
            "runtime-verifier",
            "exact-command-policy",
        ),
        PreflightGate.ATTEMPT_POLICY: (
            GateState.PASS,
            "canonical-attempt-policy",
            "attempt-verifier",
            "released-attempt-policy",
        ),
        PreflightGate.RUNTIME_CAPABILITY: (
            GateState.PASS,
            "claude-noninteractive-supported",
            "runtime-verifier",
            "authenticated-runtime",
        ),
    }


def _production_authority(
    cell: EvaluationCell,
    *,
    loaded_fixture: object,
    journey_run_id: str,
    journey_ledger: object,
    runtime_adapter: object | None = None,
    content_projection: object | None = None,
    personal_snapshot_receipt: object | None = None,
) -> _EvaluationAuthority:
    """Consume exact fixture, TASK-296, and signed content authorities."""

    from cc.core.evaluation.content_authority import (
        CanonicalContentUnavailable,
        issue_canonical_claude_content,
        verify_canonical_content_projection,
    )
    from cc.core.evaluation.fixtures import LoadedFixture, verify_loaded_fixture
    from cc.core.evaluation.journey_runtime import TcJourneyLedger
    from cc.core.evaluation.matrix import route_contract_document

    facts: dict[PreflightGate, tuple[GateState, str, str, str]] = {}
    automatic_personal_temporary = None
    automatic_personal_receipt = None
    if (
        isinstance(loaded_fixture, LoadedFixture)
        and verify_loaded_fixture(loaded_fixture)
        and (
            loaded_fixture.fixture_sha256 == cell.fixture_sha256
            and loaded_fixture.fixture.case_id == cell.case_id
            and loaded_fixture.fixture.revision == cell.revision
        )
    ):
        facts[PreflightGate.FIXTURE_CONTRACT] = (
            GateState.PASS,
            "verified",
            "fixture-loader",
            "digest-bound-fixture",
        )
    state: dict[str, object] = {}
    if isinstance(journey_ledger, TcJourneyLedger):
        state = _verified_journey_identities(journey_run_id, journey_ledger) or {}
        if (
            state.get("run_id") == journey_run_id
            and state.get("prompt_sha256") == cell.prompt_evidence_sha256
            and state.get("task_id") == cell.consumption_receipt.task_id
            and state.get("journey_evidence_sha256")
            == cell.consumption_receipt.journey_evidence_sha256
            and state.get("route_evidence_sha256")
            == cell.consumption_receipt.route_evidence_sha256
            and state.get("continuity_evidence_sha256")
            == cell.consumption_receipt.continuity_evidence_sha256
        ):
            facts[PreflightGate.JOURNEY_EVIDENCE] = (
                GateState.PASS,
                "dispatch-authorized",
                "task296-ledger",
                "verified-dispatch-ledger",
            )
    retained_content_projection = None
    content_fact = (
        GateState.FAIL,
        "signed-content-unavailable",
        "publisher",
        "canonical-signed-content",
    )
    if cell.runtime_receipt.runtime is RuntimeName.CODEX:
        from cc.core.evaluation.execution import _verify_codex_zero_call_cell

        if PreflightGate.FIXTURE_CONTRACT in facts and _verify_codex_zero_call_cell(
            cell,
            loaded_fixture,
        ):
            # Codex remains a deliberate zero-call disposition until the
            # preventive tool-registry boundary is verifier-proved. No model,
            # source projection, output, or external mutation occurs here.
            zero_call = {
                PreflightGate.ENTITLEMENT_AND_PINS: (
                    GateState.PASS,
                    "no-content-consumed",
                    "content-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.RESOLUTION_IDENTITY: (
                    GateState.PASS,
                    "no-runtime-dispatch",
                    "runtime-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.RUNTIME_ADAPTER: (
                    GateState.PASS,
                    "no-runtime-dispatch",
                    "runtime-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.JOURNEY_EVIDENCE: (
                    GateState.PASS,
                    "preregistered-route-not-dispatched",
                    "protocol-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.REQUIRED_CONTENT: (
                    GateState.PASS,
                    "no-content-consumed",
                    "content-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.SAFETY_SCAN: (
                    GateState.PASS,
                    "verified-synthetic-fixture",
                    "fixture-loader",
                    "digest-bound-fixture",
                ),
                PreflightGate.PERSONAL_NON_LEAKAGE: (
                    GateState.PASS,
                    "zero-output",
                    "privacy-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.NO_EXTERNAL_MUTATION: (
                    GateState.PASS,
                    "zero-runtime-call",
                    "runtime-verifier",
                    "zero-call-disposition",
                ),
                PreflightGate.ATTEMPT_POLICY: (
                    GateState.PASS,
                    "canonical-attempt-policy",
                    "attempt-verifier",
                    "released-attempt-policy",
                ),
                PreflightGate.RUNTIME_CAPABILITY: (
                    GateState.UNSUPPORTED,
                    "codex-no-tool-isolation-unavailable",
                    "runtime-verifier",
                    "preventive-runtime-isolation",
                ),
            }
            facts.update(zero_call)
            content_fact = facts[PreflightGate.ENTITLEMENT_AND_PINS]
        else:
            content_fact = (
                GateState.FAIL,
                "codex-zero-call-disposition-unverified",
                "content-verifier",
                "canonical-zero-call-cell",
            )
    elif PreflightGate.JOURNEY_EVIDENCE in facts:
        route = route_contract_document(cell.case_id)
        if (
            state.get("runtime") != RuntimeName.CLAUDE.value
            or state.get("variant") != cell.variant.value
            or state.get("specialist") != route["specialists"][0]
            or state.get("stage_index") != 0
        ):
            content_fact = (
                GateState.FAIL,
                "journey-content-route-mismatch",
                "content-verifier",
                "canonical-signed-content",
            )
        else:
            try:
                if (
                    content_projection is None
                    and personal_snapshot_receipt is None
                    and cell.variant.value == "F+O+D+P"
                    and cell.case_id == "eval-07"
                ):
                    import tempfile
                    from pathlib import Path

                    from cc.evaluation_fixtures.personal_snapshot import (
                        materialize_personal_snapshot,
                    )

                    automatic_personal_temporary = tempfile.TemporaryDirectory(
                        prefix=".cc-evaluation-personal-authority-"
                    )
                    private_root = Path(automatic_personal_temporary.name)
                    private_root.chmod(0o700)
                    automatic_personal_receipt = materialize_personal_snapshot(
                        private_root / "personal-content"
                    )
                    personal_snapshot_receipt = automatic_personal_receipt
                projection = content_projection
                if projection is None:
                    projection = issue_canonical_claude_content(
                        variant=cell.variant,
                        specialist=str(state["specialist"]),
                        case_id=cell.case_id,
                        personal_snapshot_receipt=personal_snapshot_receipt,
                    )
            except CanonicalContentUnavailable as exc:
                content_fact = (
                    GateState.FAIL,
                    exc.reason,
                    "content-verifier",
                    "canonical-signed-content",
                )
            except (OSError, TypeError, ValueError):
                content_fact = (
                    GateState.FAIL,
                    "signed-content-unavailable",
                    "content-verifier",
                    "canonical-signed-content",
                )
            else:
                if (
                    verify_canonical_content_projection(projection)
                    and content_receipt_identity(projection.content_receipt)
                    == content_receipt_identity(cell.content_receipt)
                    and projection.content_receipt.composed_content_sha256
                    == state.get("composed_content_sha256")
                    and [dict(item) for item in projection.knowledge_sources]
                    == state.get("sources")
                ):
                    retained_content_projection = projection
                    content_fact = (
                        GateState.PASS,
                        "signed-content-verified",
                        "content-verifier",
                        "canonical-signed-content",
                    )
                    facts.update(
                        _claude_runtime_facts(
                            cell,
                            loaded_fixture=loaded_fixture,
                            state=state,
                            projection=projection,
                            runtime_adapter=runtime_adapter,
                        )
                    )
                else:
                    projection.close()
                    content_fact = (
                        GateState.FAIL,
                        "signed-content-mismatch",
                        "content-verifier",
                        "canonical-signed-content",
                    )
    facts[PreflightGate.ENTITLEMENT_AND_PINS] = content_fact
    cleanup = None
    if automatic_personal_temporary is not None:
        if retained_content_projection is None:
            close = getattr(automatic_personal_receipt, "close", None)
            if callable(close):
                close()
            automatic_personal_temporary.cleanup()
        else:
            cleanup = automatic_personal_temporary.cleanup
    observations = tuple(
        _observation(gate, *fact)
        for gate, fact in sorted(facts.items(), key=lambda x: x[0].value)
    )
    subject = _cell_subject(cell)
    return _issue_evaluation_authority(
        subject,
        evaluate_preflight(observations, subject_sha256=subject),
        content_projection=retained_content_projection,
        cleanup=cleanup,
    )
