"""Backend selection factory for cc memory (TASK-43).

resolve_backend() reads `memory.embedding_model` via config and returns
the appropriate SearchBackend:

    - "none" (default) → FTS5Backend()  (no embedding code touched, no
      sentence-transformers import, BYTE-IDENTICAL to pre-TASK-43 behaviour)
    - Any other model name → attempt EmbeddingBackend; on any failure
      log a WARNING and fall back to FTS5Backend.

This is the SINGLE wiring point for backend selection.

Default-off guarantee:
    When memory.embedding_model == "none", this module's resolve_backend()
    returns FTS5Backend() and imports NOTHING from embedding_backend or
    sentence-transformers.  The off-path is dependency-free.
"""

from __future__ import annotations

import logging

from cc.core.memory_index import FTS5Backend, SearchBackend

_log = logging.getLogger(__name__)

# Module-level cache: resolved once per process (avoids re-reading config
# and re-loading the model on every call).  Reset via _reset_cache() in tests.
_cached_backend: SearchBackend | None = None
_cached_model: str | None = None  # the model name used when cache was built


def resolve_backend(
    *,
    _model_override: str | None = None,
    _force_reload: bool = False,
) -> SearchBackend:
    """Return the active SearchBackend based on config.

    Args:
        _model_override: Override model name (used in tests; skips config read).
        _force_reload:   Bypass the module-level cache (used in tests).

    Returns:
        FTS5Backend when model is "none" or embedding loading fails.
        EmbeddingBackend otherwise.
    """
    global _cached_backend, _cached_model

    # Determine the model name
    if _model_override is not None:
        model = _model_override
    else:
        from cc.core.config import resolve_key

        model = str(resolve_key("memory.embedding_model") or "none")

    # Return cached backend if model unchanged and not forced
    if not _force_reload and _cached_backend is not None and _cached_model == model:
        return _cached_backend

    backend = _build_backend(model)
    _cached_backend = backend
    _cached_model = model
    return backend


def _build_backend(model: str) -> SearchBackend:
    """Construct the backend for *model* (no caching here)."""
    if model.lower() == "none":
        return FTS5Backend()

    # Enabled path — lazily import embedding code
    try:
        from cc.core.embedding_backend import EmbeddingBackend, EmbeddingUnavailable
    except ImportError as exc:
        _log.warning(
            "Embedding backend module unavailable; falling back to FTS5 keyword search: %s",
            exc,
        )
        return FTS5Backend()

    try:
        from cc.core.config import resolve_key

        threshold = float(resolve_key("memory.default_threshold") or 0.7)
        backend = EmbeddingBackend(model, threshold=threshold)
        _log.info("Embedding backend active: model=%r threshold=%s", model, threshold)
        return backend
    except EmbeddingUnavailable as exc:
        _log.warning(
            "Embeddings requested (model=%r) but unavailable; falling back to FTS5 keyword search: %s",
            model,
            exc,
        )
        return FTS5Backend()
    except Exception as exc:  # noqa: BLE001 — catch-all for unexpected model errors
        _log.warning(
            "Unexpected error loading embedding backend (model=%r); falling back to FTS5: %s",
            model,
            exc,
        )
        return FTS5Backend()


def _reset_cache() -> None:
    """Clear the module-level backend cache (for use in tests only)."""
    global _cached_backend, _cached_model
    _cached_backend = None
    _cached_model = None
