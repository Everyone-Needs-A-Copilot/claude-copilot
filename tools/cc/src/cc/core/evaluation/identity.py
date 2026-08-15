"""Canonical identities for evaluation runtime and consumption evidence.

The constructors in this module only bind verifier-produced facts.  They do
not resolve content, infer entitlement, or call a runtime.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cc.core.evaluation.models import (
    ConsumptionReceipt,
    ContentReceipt,
    LayerContentReceipt,
    RuntimeReceipt,
)
from cc.core.evaluation.schema import canonical_sha256


def runtime_receipt_document(receipt: RuntimeReceipt) -> dict[str, Any]:
    return {
        "runtime": receipt.runtime.value,
        "executable_sha256": receipt.executable_sha256,
        "runtime_version": receipt.runtime_version,
        "model_version": receipt.model_version,
        "tool_availability": list(receipt.tool_availability),
        "adapter_name": receipt.adapter_name,
        "adapter_version": receipt.adapter_version,
        "capability_flags": list(receipt.capability_flags),
    }


def runtime_receipt_identity(receipt: RuntimeReceipt) -> str:
    return canonical_sha256(runtime_receipt_document(receipt))


def _layer_document(receipt: LayerContentReceipt) -> dict[str, Any]:
    return {
        "product": receipt.product,
        "tier": receipt.tier,
        "source_layer_identifier": receipt.source_layer_identifier,
        "source_runtime": receipt.source_runtime,
        "source_adapter_version": receipt.source_adapter_version,
        "repository_identifier": receipt.repository_identifier,
        "immutable_ref": receipt.immutable_ref,
        "tree_sha256": receipt.tree_sha256,
        "source_tree": receipt.source_tree,
        "signer_identity": receipt.signer_identity,
        "policy_sha256": receipt.policy_sha256,
        "manifest_sha256": receipt.manifest_sha256,
        "lock_sha256": receipt.lock_sha256,
        "contribution_ids": list(receipt.contribution_ids),
        "content_digests": list(receipt.content_digests),
        "resolution_action": receipt.resolution_action,
        "materialized_destinations": list(receipt.materialized_destinations),
    }


def content_receipt_document(receipt: ContentReceipt) -> dict[str, Any]:
    return {
        "variant": receipt.variant.value,
        "entitlement_receipt_sha256": receipt.entitlement_receipt_sha256,
        "layers": [_layer_document(layer) for layer in receipt.layers],
        "composed_content_sha256": receipt.composed_content_sha256,
        "materialization_sha256": receipt.materialization_sha256,
    }


def content_receipt_identity(receipt: ContentReceipt) -> str:
    return canonical_sha256(content_receipt_document(receipt))


def prepared_sources_match_content_receipt(
    receipt: ContentReceipt,
    sources: Sequence[Mapping[str, Any]],
) -> bool:
    """Require exact one-to-one source coverage for consumed layer products.

    A journey source is deliberately narrower than a layer product receipt: it
    names one contribution and its digest. Every such source must resolve to
    exactly one signed product identity, and every contribution declared by a
    product receipt must appear exactly once in the prepared invocation.
    """

    if not sources:
        return False
    unmatched = list(sources)
    contributing_layers = tuple(
        layer
        for layer in receipt.layers
        if layer.resolution_action in {"accumulated", "selected"}
    )
    for layer in contributing_layers:
        matching = [
            source
            for source in unmatched
            if source.get("repository") == layer.repository_identifier
            and source.get("layer") == layer.source_layer_identifier
            and source.get("tier") == layer.tier
            and source.get("runtime") == layer.source_runtime
            and source.get("adapter_version") == layer.source_adapter_version
            and source.get("ref") == layer.immutable_ref
            and source.get("tree") == (layer.source_tree or layer.tree_sha256)
            and source.get("signer") == layer.signer_identity
        ]
        if not matching:
            return False
        contribution_pairs = tuple(
            sorted(
                (
                    str(source.get("contribution", "")),
                    str(source.get("content_sha256", "")),
                )
                for source in matching
            )
        )
        declared_pairs = tuple(
            sorted(zip(layer.contribution_ids, layer.content_digests, strict=True))
        )
        if contribution_pairs != declared_pairs:
            return False
        for source in matching:
            unmatched.remove(source)
    return not unmatched


def invocation_envelope_identity(
    *,
    runtime_receipt_sha256: str,
    content_receipt_sha256: str,
    composed_content_sha256: str,
    prompt_evidence_sha256: str,
    journey_evidence_sha256: str,
) -> str:
    return canonical_sha256(
        {
            "runtime_receipt_sha256": runtime_receipt_sha256,
            "content_receipt_sha256": content_receipt_sha256,
            "composed_content_sha256": composed_content_sha256,
            "prompt_evidence_sha256": prompt_evidence_sha256,
            "journey_evidence_sha256": journey_evidence_sha256,
        }
    )


def build_consumption_receipt(
    *,
    task_id: int,
    runtime_receipt: RuntimeReceipt,
    content_receipt: ContentReceipt,
    prompt_evidence_sha256: str,
    journey_evidence_sha256: str,
    route_evidence_sha256: str,
    continuity_evidence_sha256: str,
) -> ConsumptionReceipt:
    runtime_sha256 = runtime_receipt_identity(runtime_receipt)
    content_sha256 = content_receipt_identity(content_receipt)
    return ConsumptionReceipt(
        task_id=task_id,
        runtime_receipt_sha256=runtime_sha256,
        content_receipt_sha256=content_sha256,
        prompt_evidence_sha256=prompt_evidence_sha256,
        invocation_envelope_sha256=invocation_envelope_identity(
            runtime_receipt_sha256=runtime_sha256,
            content_receipt_sha256=content_sha256,
            composed_content_sha256=content_receipt.composed_content_sha256,
            prompt_evidence_sha256=prompt_evidence_sha256,
            journey_evidence_sha256=journey_evidence_sha256,
        ),
        journey_evidence_sha256=journey_evidence_sha256,
        route_evidence_sha256=route_evidence_sha256,
        continuity_evidence_sha256=continuity_evidence_sha256,
    )


def consumption_receipt_document(receipt: ConsumptionReceipt) -> dict[str, Any]:
    return {
        "task_id": receipt.task_id,
        "runtime_receipt_sha256": receipt.runtime_receipt_sha256,
        "content_receipt_sha256": receipt.content_receipt_sha256,
        "prompt_evidence_sha256": receipt.prompt_evidence_sha256,
        "invocation_envelope_sha256": receipt.invocation_envelope_sha256,
        "journey_evidence_sha256": receipt.journey_evidence_sha256,
        "route_evidence_sha256": receipt.route_evidence_sha256,
        "continuity_evidence_sha256": receipt.continuity_evidence_sha256,
    }


def consumption_receipt_identity(receipt: ConsumptionReceipt) -> str:
    return canonical_sha256(consumption_receipt_document(receipt))
