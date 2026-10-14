from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from cc.core.evaluation import prepared_codex as prepared_module
from cc.core.evaluation.fixtures import LoadedFixture
from cc.core.evaluation.matrix import MatrixCellPlan, build_matrix
from cc.core.evaluation.models import LayerVariant, RuntimeName
from cc.core.evaluation.prepared_codex import (
    PREPARED_CODEX_ADAPTER_NAME,
    PREPARED_CODEX_ADAPTER_SHA256,
    PREPARED_CODEX_ADAPTER_VERSION,
    PREPARED_CODEX_MODEL,
    PREPARED_CODEX_MODEL_SHA256,
    PreparedCodexCellDeclaration,
    declare_prepared_codex_cell,
    prepared_codex_declaration_document,
    prepared_codex_declaration_document_is_well_formed,
)
from cc.core.evaluation.schema import canonical_sha256
from cc.evaluation_fixtures import PACKAGED_MATRIX_SHA256, packaged_cases_root


def _selection() -> tuple[MatrixCellPlan, LoadedFixture]:
    matrix, fixtures = build_matrix(packaged_cases_root())
    plan = next(
        item
        for item in matrix.cells
        if item.case_id == "eval-01"
        and item.variant is LayerVariant.FOUNDATION
        and item.runtime is RuntimeName.CODEX
    )
    loaded = next(item for item in fixtures if item.fixture.case_id == plan.case_id)
    return plan, loaded


def _arguments(**changes: object) -> dict[str, object]:
    plan, loaded = _selection()
    values: dict[str, object] = {
        "case_id": plan.case_id,
        "variant": plan.variant,
        "role": plan.role,
        "fixture_sha256": loaded.fixture_sha256,
        "route_sha256": plan.route_contract_sha256,
        "journey_sha256": canonical_sha256({"subject": "journey"}),
        "ledger_sha256": canonical_sha256({"subject": "ledger"}),
        "prompt_sha256": canonical_sha256({"subject": "prompt"}),
        "model_sha256": PREPARED_CODEX_MODEL_SHA256,
        "adapter_sha256": PREPARED_CODEX_ADAPTER_SHA256,
        "canonical_content_projection_sha256": canonical_sha256(
            {"subject": "canonical-content-projection"}
        ),
        "artifact_root_sha256": canonical_sha256({"subject": "artifact-root"}),
        "staged_executable_sha256": canonical_sha256({"subject": "staged-executable"}),
        "catalog_sha256": canonical_sha256({"subject": "catalog"}),
    }
    values.update(changes)
    return values


def _declare(**changes: object) -> PreparedCodexCellDeclaration:
    return declare_prepared_codex_cell(**_arguments(**changes))  # type: ignore[arg-type]


def test_declaration_binds_packaged_plan_and_explicitly_denies_authority() -> None:
    plan, _loaded = _selection()
    declaration = _declare()
    document = prepared_codex_declaration_document(declaration)

    assert declaration.authority == "none"
    assert declaration.dispatch_authorized is False
    assert declaration.matrix_sha256 == PACKAGED_MATRIX_SHA256
    assert declaration.case_id == plan.case_id
    assert declaration.revision == plan.revision
    assert declaration.variant is plan.variant
    assert declaration.runtime is RuntimeName.CODEX
    assert declaration.role == plan.role
    assert declaration.fixture_packet_sha256 == plan.fixture_packet_sha256
    assert declaration.route_classification == plan.route_classification
    assert declaration.expected_specialist == plan.expected_specialist
    assert declaration.route_contract_sha256 == plan.route_contract_sha256
    assert declaration.route_sha256 == plan.route_contract_sha256
    assert declaration.model == PREPARED_CODEX_MODEL
    assert declaration.adapter_name == PREPARED_CODEX_ADAPTER_NAME
    assert declaration.adapter_version == PREPARED_CODEX_ADAPTER_VERSION
    assert document["authority"] == "none"
    assert document["dispatch_authorized"] is False
    assert document["declaration_sha256"] == canonical_sha256(
        {key: value for key, value in document.items() if key != "declaration_sha256"}
    )
    assert prepared_codex_declaration_document_is_well_formed(document)


def test_policy_and_example_declaration_hashes_are_frozen() -> None:
    declaration = _declare()

    assert PREPARED_CODEX_MODEL_SHA256 == (
        "d0f86084c9190928daebbb6e859b9c0353c4bce5308cfd475ed4f62588c06fbe"
    )
    assert PREPARED_CODEX_ADAPTER_SHA256 == (
        "781672c20be5ac17f7f2cff7f321783be64553de320b7d9ec934bb9c6d059b80"
    )
    assert declaration.declaration_sha256 == (
        "af96830d076fa75ecd2e7d82e93bab6ace828f5c12e7cef6d8b60b17e950e56f"
    )


def test_all_fourteen_packaged_codex_declarations_are_structurally_unique() -> None:
    matrix, fixtures = build_matrix(packaged_cases_root())
    loaded_by_case = {item.fixture.case_id: item for item in fixtures}
    declarations = []

    for plan in matrix.cells:
        if plan.runtime is not RuntimeName.CODEX:
            continue
        selector = {
            "case_id": plan.case_id,
            "variant": plan.variant.value,
            "role": plan.role,
        }
        declarations.append(
            declare_prepared_codex_cell(
                case_id=plan.case_id,
                variant=plan.variant,
                role=plan.role,
                fixture_sha256=loaded_by_case[plan.case_id].fixture_sha256,
                route_sha256=plan.route_contract_sha256,
                journey_sha256=canonical_sha256({**selector, "subject": "journey"}),
                ledger_sha256=canonical_sha256({**selector, "subject": "ledger"}),
                prompt_sha256=canonical_sha256({**selector, "subject": "prompt"}),
                model_sha256=PREPARED_CODEX_MODEL_SHA256,
                adapter_sha256=PREPARED_CODEX_ADAPTER_SHA256,
                canonical_content_projection_sha256=canonical_sha256(
                    {**selector, "subject": "canonical-content-projection"}
                ),
                artifact_root_sha256=canonical_sha256(
                    {**selector, "subject": "artifact-root"}
                ),
                staged_executable_sha256=canonical_sha256(
                    {**selector, "subject": "staged-executable"}
                ),
                catalog_sha256=canonical_sha256({**selector, "subject": "catalog"}),
            )
        )

    documents = [prepared_codex_declaration_document(item) for item in declarations]
    assert len(declarations) == 14
    assert len({item.plan_sha256 for item in declarations}) == 14
    assert len({item.declaration_sha256 for item in declarations}) == 14
    assert all(item.authority == "none" for item in declarations)
    assert not any(item.dispatch_authorized for item in declarations)
    assert all(
        prepared_codex_declaration_document_is_well_formed(item) for item in documents
    )


def test_declarer_rederives_plan_and_rejects_wrong_or_caller_supplied_plan() -> None:
    plan, _loaded = _selection()

    with pytest.raises(ValueError, match="selector is not preregistered"):
        _declare(role="layered")
    with pytest.raises(ValueError, match="selector is not preregistered"):
        _declare(variant=LayerVariant.DEPARTMENT)
    with pytest.raises(TypeError, match="unexpected keyword argument 'plan'"):
        declare_prepared_codex_cell(
            **_arguments(),
            plan=replace(plan),
        )


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("fixture_sha256", "packaged subject"),
        ("route_sha256", "packaged subject"),
        ("model_sha256", "runtime policy subject"),
        ("adapter_sha256", "runtime policy subject"),
    ),
)
def test_declarer_rejects_mismatched_packaged_and_policy_subjects(
    field_name: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _declare(**{field_name: canonical_sha256({"mismatch": field_name})})


def test_declarer_rejects_malformed_digest_subject() -> None:
    with pytest.raises(ValueError, match="journey_sha256 must be a SHA-256 digest"):
        _declare(journey_sha256="not-a-digest")


def test_frozen_value_copies_are_equivalent_not_capabilities() -> None:
    declaration = _declare()
    copies = (copy.copy(declaration), copy.deepcopy(declaration), replace(declaration))

    assert all(item == declaration for item in copies)
    assert all(
        prepared_codex_declaration_document(item)
        == prepared_codex_declaration_document(declaration)
        for item in copies
    )
    assert all(item.authority == "none" for item in copies)
    assert not any(item.dispatch_authorized for item in copies)


def test_mutated_value_and_recomputed_hash_remains_nonauthorizing() -> None:
    declaration = _declare()
    object.__setattr__(
        declaration,
        "journey_sha256",
        canonical_sha256({"different": "journey"}),
    )
    object.__setattr__(
        declaration,
        "declaration_sha256",
        canonical_sha256(prepared_module._declaration_body(declaration)),
    )
    document = prepared_codex_declaration_document(declaration)

    assert prepared_codex_declaration_document_is_well_formed(document)
    assert document["authority"] == "none"
    assert document["dispatch_authorized"] is False


def test_self_rehashed_document_remains_structural_and_nonauthorizing() -> None:
    document = prepared_codex_declaration_document(_declare())
    altered = dict(document)
    altered["journey_sha256"] = canonical_sha256({"different": "journey"})
    altered["declaration_sha256"] = canonical_sha256(
        {key: value for key, value in altered.items() if key != "declaration_sha256"}
    )

    assert prepared_codex_declaration_document_is_well_formed(altered)
    assert altered["authority"] == "none"
    assert altered["dispatch_authorized"] is False
    assert not hasattr(prepared_module, "load_prepared_codex_declaration")


def test_document_is_closed_value_suppressing_and_cannot_claim_authority() -> None:
    document = prepared_codex_declaration_document(_declare())
    rendered = str(document)
    extended = {**document, "artifact_root": "/private/evaluation"}
    forged_authority = {**document, "authority": "verifier"}
    forged_authority["declaration_sha256"] = canonical_sha256(
        {
            key: value
            for key, value in forged_authority.items()
            if key != "declaration_sha256"
        }
    )

    assert not prepared_codex_declaration_document_is_well_formed(extended)
    assert not prepared_codex_declaration_document_is_well_formed(forged_authority)
    assert "problem_statement" not in rendered
    assert "knowledge_payload" not in rendered
    assert "prompt_text" not in rendered
    assert "artifact_root" not in document
    assert "staged_executable" not in document
    assert "catalog" not in document


def test_public_surface_has_no_lifecycle_or_authority_semantics() -> None:
    declaration = _declare()
    public_names = set(prepared_module.__all__)
    prohibited = (
        "is_current",
        "consume",
        "authorize",
        "verify",
        "identity",
        "issuer",
    )

    assert not any(token in name for name in public_names for token in prohibited)
    assert not any(hasattr(declaration, name) for name in prohibited)
    assert not hasattr(prepared_module, "_ISSUED")
    assert not hasattr(prepared_module, "_CONSUMED")
    assert declare_prepared_codex_cell.__closure__ is None
    assert prepared_codex_declaration_document.__closure__ is None
