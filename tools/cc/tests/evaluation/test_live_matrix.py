from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cc.core.evaluation.journey_runtime import PreparedInvocation
from cc.core.evaluation.matrix import (
    build_matrix,
    build_runtime_prompt,
    matrix_document,
    prompt_evidence_identity,
    route_contract_document,
    runtime_configuration_identity,
)
from cc.core.evaluation.models import LayerVariant, RuntimeName

FIXTURES = Path(__file__).parent / "fixtures" / "cases"


def test_loaded_fixture_copy_cannot_substitute_verified_runtime_bytes() -> None:
    _, loaded = build_matrix(FIXTURES)
    original = loaded[0]
    forged_evidence = replace(original.evidence[0], content=b"substituted bytes")
    forged = replace(
        original,
        evidence=(forged_evidence, *original.evidence[1:]),
    )

    with pytest.raises(ValueError, match="not verifier-issued"):
        prompt_evidence_identity(forged)
    with pytest.raises(ValueError, match="not verifier-issued"):
        build_runtime_prompt(
            forged,
            variant=LayerVariant.FOUNDATION,
            runtime=RuntimeName.CLAUDE,
            prepared=_prepared(),
        )


def _prepared(
    runtime: str = "claude",
    variant: LayerVariant = LayerVariant.FOUNDATION,
    specialist: str = "sd",
    stage_index: int = 0,
) -> PreparedInvocation:
    knowledge = "Synthetic authenticated foundation method."
    marker = "1" * 48
    tiers = {
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
    return PreparedInvocation(
        run_id="j2-285-" + "2" * 24,
        specialist=specialist,
        variant=variant.value,
        runtime=runtime,
        stage_index=stage_index,
        invocation_marker=marker,
        knowledge_payload=knowledge,
        agent_prompt_fragment=(
            f"CC-JOURNEY-INVOCATION: {marker}\n"
            "CC-JOURNEY-KNOWLEDGE-BEGIN\n"
            f"{knowledge}\n"
            "CC-JOURNEY-KNOWLEDGE-END"
        ),
        composed_content_sha256=hashlib.sha256(knowledge.encode()).hexdigest(),
        sources=tuple(
            {
                "layer": f"synthetic-{tier}",
                "tier": tier,
                "repository": f"synthetic/{tier}",
                "ref": f"refs/tags/synthetic-{tier}-v1",
                "tree": str(index + 3) * 40,
                "signer": "SHA256:SYNTHETIC",
                "contribution": f"{tier}/{specialist}.extension.md",
                "content_sha256": str(index + 4) * 64,
                "runtime": runtime,
                "adapter_version": "knowledge-v1",
            }
            for index, tier in enumerate(tiers)
        ),
    )


def test_matrix_is_exactly_28_preregistered_runtime_variant_cells() -> None:
    matrix, loaded = build_matrix(FIXTURES)

    assert len(loaded) == 7
    assert len(matrix.cells) == 28
    assert (
        len(
            {
                (item.case_id, item.variant.value, item.runtime.value)
                for item in matrix.cells
            }
        )
        == 28
    )
    assert [item.case_id for item in matrix.cells[::4]] == [
        f"eval-{index:02d}" for index in range(1, 8)
    ]
    for case_id in ("eval-01", "eval-02", "eval-03", "eval-04", "eval-06"):
        variants = {item.variant for item in matrix.cells if item.case_id == case_id}
        assert variants == {LayerVariant.FOUNDATION, LayerVariant.ORGANIZATION}
    assert {item.variant for item in matrix.cells if item.case_id == "eval-05"} == {
        LayerVariant.FOUNDATION,
        LayerVariant.DEPARTMENT,
    }
    assert {item.variant for item in matrix.cells if item.case_id == "eval-07"} == {
        LayerVariant.DEPARTMENT,
        LayerVariant.PERSONAL,
    }
    assert {item.runtime for item in matrix.cells} == {
        RuntimeName.CLAUDE,
        RuntimeName.CODEX,
    }
    assert (
        matrix.matrix_sha256
        == "0c844795668aa2dc40596975ba5e20d3ee2fe345583149d20c9c8a07ef6688f6"
    )
    document = matrix_document(matrix)
    assert document["matrix_sha256"] == matrix.matrix_sha256
    assert not any(key in document for key in ("score", "rank", "winner"))


def test_matrix_preregisters_exact_variant_invariant_case_routes() -> None:
    matrix, _loaded = build_matrix(FIXTURES)
    expected = {
        "eval-01": ("service-design", "sd"),
        "eval-02": ("organizational-design", "sd"),
        "eval-03": ("ui-design", "uids"),
        "eval-04": ("creative-direction", "cco"),
        "eval-05": ("accounting-advisory", "cpa"),
        "eval-06": ("technical-architecture", "ta"),
        "eval-07": ("documentation", "doc"),
    }

    for case_id, (classification, specialist) in expected.items():
        route = route_contract_document(case_id)
        assert route == {
            "schema_version": "task296-evaluation-route-v1",
            "case_id": case_id,
            "revision": 1,
            "classification": classification,
            "specialists": [specialist],
            "stages": [
                {
                    "stage_index": 0,
                    "specialist": specialist,
                    "reason": "protocol-supplied",
                }
            ],
            "route_contract_sha256": route["route_contract_sha256"],
        }
        matching = [cell for cell in matrix.cells if cell.case_id == case_id]
        assert {cell.route_classification for cell in matching} == {classification}
        assert {cell.expected_specialist for cell in matching} == {specialist}
        assert {cell.route_contract_sha256 for cell in matching} == {
            route["route_contract_sha256"]
        }

    assert matrix_document(matrix)["route_contracts"] == [
        route_contract_document(case_id) for case_id in expected
    ]


def test_matrix_cell_rejects_route_contract_substitution() -> None:
    matrix, _loaded = build_matrix(FIXTURES)
    cell = next(item for item in matrix.cells if item.case_id == "eval-03")

    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(cell, expected_specialist="sd")
    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(cell, route_classification="service-design")
    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(cell, route_contract_sha256="f" * 64)
    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(cell, fixture_packet_sha256="f" * 64)


def test_runtime_prompt_binds_prepared_knowledge_and_excludes_private_oracle() -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    fixture = loaded[0]
    prompt = build_runtime_prompt(
        fixture,
        variant=LayerVariant.FOUNDATION,
        runtime=RuntimeName.CLAUDE,
        prepared=_prepared(),
    )

    assert "CC-JOURNEY-KNOWLEDGE-BEGIN" in prompt.system_context_text
    assert "CC-EVALUATION-RUNTIME-POLICY" in prompt.system_context_text
    assert "CC-JOURNEY-KNOWLEDGE-BEGIN" not in prompt.user_prompt_text
    assert "foundation method" not in prompt.user_prompt_text
    assert fixture.fixture.problem_statement in prompt.user_prompt_text
    runtime_input = json.loads(prompt.user_prompt_text)
    assert [item["content"] for item in runtime_input["evidence"]] == [
        item.content.decode() for item in fixture.evidence
    ]
    assert fixture.oracle.path not in prompt.user_prompt_text
    assert fixture.oracle.sha256 not in prompt.user_prompt_text
    assert fixture.oracle.content.decode() not in prompt.user_prompt_text
    assert (
        prompt.route_contract_sha256
        == route_contract_document("eval-01")["route_contract_sha256"]
    )
    assert (
        prompt.fixture_packet_sha256
        == matrix_document(_matrix)["fixture_packets"][0]["fixture_packet_sha256"]
    )


def test_foundation_prompt_accepts_authenticated_absence_of_knowledge_content() -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    prepared = replace(_prepared(), sources=())

    prompt = build_runtime_prompt(
        loaded[0],
        variant=LayerVariant.FOUNDATION,
        runtime=RuntimeName.CLAUDE,
        prepared=prepared,
    )

    assert prompt.source_receipts == ()
    assert prompt.source_runtimes == ()
    assert prompt.composed_content_sha256 == prepared.composed_content_sha256


def test_runtime_configuration_identity_binds_route_contract() -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    prompt = build_runtime_prompt(
        loaded[2],
        variant=LayerVariant.FOUNDATION,
        runtime=RuntimeName.CLAUDE,
        prepared=_prepared(specialist="uids"),
    )
    original_identity = runtime_configuration_identity(prompt)

    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(prompt, specialist="sd")
    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(prompt, route_contract_sha256="f" * 64)
    with pytest.raises(ValueError, match="route is not preregistered"):
        replace(prompt, fixture_packet_sha256="f" * 64)
    assert runtime_configuration_identity(prompt) == original_identity


@pytest.mark.parametrize(
    ("fixture_index", "expected_specialist"),
    ((2, "uids"), (3, "cco"), (4, "cpa")),
)
def test_runtime_prompt_rejects_sd_for_specialist_bound_cases(
    fixture_index: int,
    expected_specialist: str,
) -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    fixture = loaded[fixture_index]

    with pytest.raises(ValueError, match="preregistered route"):
        build_runtime_prompt(
            fixture,
            variant=fixture.fixture.layer_variants[0],
            runtime=RuntimeName.CLAUDE,
            prepared=_prepared(specialist="sd"),
        )

    prompt = build_runtime_prompt(
        fixture,
        variant=fixture.fixture.layer_variants[0],
        runtime=RuntimeName.CLAUDE,
        prepared=_prepared(specialist=expected_specialist),
    )
    assert prompt.specialist == expected_specialist


def test_runtime_prompt_rejects_wrong_route_stage() -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    with pytest.raises(ValueError, match="preregistered route"):
        build_runtime_prompt(
            loaded[0],
            variant=LayerVariant.FOUNDATION,
            runtime=RuntimeName.CLAUDE,
            prepared=_prepared(stage_index=1),
        )


def test_runtime_prompt_rejects_nonmatrix_cell_and_changed_composition() -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    fixture = loaded[0]
    with pytest.raises(ValueError, match="outside"):
        build_runtime_prompt(
            fixture,
            variant=LayerVariant.DEPARTMENT,
            runtime=RuntimeName.CLAUDE,
            prepared=_prepared(),
        )
    changed = _prepared()
    changed = PreparedInvocation(
        **{
            **changed.__dict__,
            "composed_content_sha256": "f" * 64,
        }
    )
    with pytest.raises(ValueError, match="authenticated content"):
        build_runtime_prompt(
            fixture,
            variant=LayerVariant.FOUNDATION,
            runtime=RuntimeName.CLAUDE,
            prepared=changed,
        )


@pytest.mark.parametrize(
    ("variant", "runtime", "prepared"),
    (
        (
            LayerVariant.ORGANIZATION,
            RuntimeName.CLAUDE,
            _prepared(variant=LayerVariant.FOUNDATION),
        ),
        (
            LayerVariant.FOUNDATION,
            RuntimeName.CLAUDE,
            _prepared(runtime="codex"),
        ),
    ),
)
def test_runtime_prompt_rejects_prepared_variant_or_runtime_substitution(
    variant: LayerVariant,
    runtime: RuntimeName,
    prepared: PreparedInvocation,
) -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    with pytest.raises(ValueError, match="authenticated content"):
        build_runtime_prompt(
            loaded[0],
            variant=variant,
            runtime=runtime,
            prepared=prepared,
        )


@pytest.mark.parametrize(
    ("variant", "fixture_index", "specialist"),
    (
        (LayerVariant.FOUNDATION, 0, "sd"),
        (LayerVariant.ORGANIZATION, 0, "sd"),
        (LayerVariant.DEPARTMENT, 4, "cpa"),
        (LayerVariant.PERSONAL, 6, "doc"),
    ),
)
def test_runtime_prompt_accepts_only_applicable_knowledge_tier_subset(
    variant: LayerVariant,
    fixture_index: int,
    specialist: str,
) -> None:
    _matrix, loaded = build_matrix(FIXTURES)
    prepared = _prepared(variant=variant, specialist=specialist)
    prompt = build_runtime_prompt(
        loaded[fixture_index],
        variant=variant,
        runtime=RuntimeName.CLAUDE,
        prepared=prepared,
    )
    assert {source["tier"] for source in prompt.source_receipts} == {
        source["tier"] for source in prepared.sources
    }

    reduced = build_runtime_prompt(
        loaded[fixture_index],
        variant=variant,
        runtime=RuntimeName.CLAUDE,
        prepared=PreparedInvocation(
            **{
                **prepared.__dict__,
                "sources": prepared.sources[:-1],
            }
        ),
    )
    assert reduced.source_receipts == prepared.sources[:-1]

    if variant is not LayerVariant.PERSONAL:
        extra_tier = {
            LayerVariant.FOUNDATION: "organization",
            LayerVariant.ORGANIZATION: "department",
            LayerVariant.DEPARTMENT: "personal",
        }[variant]
        extra = {
            **prepared.sources[-1],
            "layer": f"synthetic-{extra_tier}",
            "tier": extra_tier,
            "repository": f"synthetic/{extra_tier}",
        }
        with pytest.raises(ValueError, match="authenticated content"):
            build_runtime_prompt(
                loaded[fixture_index],
                variant=variant,
                runtime=RuntimeName.CLAUDE,
                prepared=PreparedInvocation(
                    **{
                        **prepared.__dict__,
                        "sources": prepared.sources + (extra,),
                    }
                ),
            )
