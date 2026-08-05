"""Bounded Claude Code proposal preparation for project reconciliation.

Claude never receives a project path, project-authored content, a command, an
operation payload, or write authority.  Python freshly inspects the selected
projects, builds a private catalog of closed recipe choices, and sends Claude a
content-free packet containing opaque references only.  Claude may select one
offered candidate per component; Python then rebuilds and verifies the normal
reconciliation plan before issuing an opaque proposal capability.
"""

from __future__ import annotations

import json
import os
import re
import resource
import secrets
import signal
import stat
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlsplit

from cc.core.ecosystem.assistant_job_store import (
    AssistantAlreadyUsed,
    AssistantBindingMismatch,
    AssistantExpired,
    AssistantNotFound,
    AssistantStoreError,
    claim_session,
    complete_session,
    create_session,
    fingerprint,
    issue_proposal,
    load_progress,
    load_proposal,
    load_session,
    record_progress,
    session_directory,
)
from cc.core.ecosystem.reconciliation_types import (
    RECONCILIATION_SCHEMA_VERSION,
    ComponentRoute,
    ReconciliationRequest,
    canonical_request_json,
    parse_reconciliation_request,
)
from cc.core.executables import resolve_executable

_SESSION_ID = re.compile(r"^session_[0-9a-f]{32}$")
_PROPOSAL_ID = re.compile(r"^proposal_[0-9a-f]{32}$")
_CANDIDATE_ID = re.compile(r"^candidate_[0-9a-f]{64}$")
_PROJECT_REF = re.compile(r"^project_[0-9a-f]{32}$")
_POLICY = {
    "schema_version": "1.0",
    "policy": "python-owned-bounded-candidate-selection",
    "assistant_may_author": [],
    "assistant_may_select": ["candidate_id"],
}
_POLICY_FINGERPRINT = fingerprint(_POLICY)
_ASSISTANT_CLAUDE_RECIPE = "claude.assistant-preserve-entry.v1"
_STANDARD_CLAUDE_RECIPE = "claude.customized-preserve-entry.v1"
_MAX_OUTPUT_BYTES = 1_048_576
_MAX_JSON_DEPTH = 12
_MAX_JSON_NODES = 2_000
_RUN_TIMEOUT_SECONDS = 900
_SAFE_WRAPPER_KEYS = frozenset(
    {
        "type",
        "subtype",
        "is_error",
        "duration_ms",
        "duration_api_ms",
        "num_turns",
        "stop_reason",
        "result",
        "session_id",
        "total_cost_usd",
        "usage",
        "modelUsage",
        "permission_denials",
        "terminal_reason",
        "fast_mode_state",
        "fast_mode_disabled_reason",
        "api_error_status",
        "ttft_ms",
        "ttft_stream_ms",
        "time_to_request_ms",
        "uuid",
        "structured_output",
    }
)
_PROHIBITED_ASSISTANT_KEYS = frozenset(
    {"command", "path", "content", "patch", "operation"}
)


def _reconciliation_error(code: str, detail: str, *, exit_code: int = 1) -> Exception:
    # Imported lazily because reconciliation.py imports this module lazily when
    # resolving a proposal.
    from cc.core.ecosystem.reconciliation import ReconciliationError

    return ReconciliationError(code, detail, exit_code=exit_code)


def _timestamp(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _progress_report(
    progress: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    started = datetime.fromisoformat(str(progress["started_at"]).replace("Z", "+00:00"))
    updated = datetime.fromisoformat(str(progress["updated_at"]).replace("Z", "+00:00"))
    stage = str(progress["stage"])
    age = max(0, int((current.astimezone(timezone.utc) - updated).total_seconds()))
    elapsed = max(0, int((current.astimezone(timezone.utc) - started).total_seconds()))
    if stage == "session-prepared":
        liveness = "waiting"
        detail = "The bounded Claude Code session is prepared and has not started yet."
    elif stage == "claude-code-running" and age > 10:
        liveness = "stale"
        detail = "Claude Code is still marked as running, but Python has not recorded a recent heartbeat."
    elif stage == "claude-code-running":
        liveness = "active"
        detail = "Claude Code is choosing only among the bounded Python candidates."
    elif stage == "python-validating-selections":
        liveness = "active"
        detail = "Python is validating Claude Code's bounded selections."
    elif stage == "python-validating-plan":
        liveness = "active"
        detail = "Python is rebuilding and validating the exact project plan."
    elif stage == "ready":
        liveness = "complete"
        detail = "Python validated the exact plan and it is ready for review."
    else:
        liveness = "blocked"
        detail = "Preparation stopped safely. No project was changed."
    return {
        "stage": stage,
        "liveness": liveness,
        "detail": detail,
        "started_at": progress["started_at"],
        "last_activity_at": progress["updated_at"],
        "elapsed_seconds": elapsed,
        "selected_project_count": progress["selected_project_count"],
        "candidate_group_count": progress["candidate_group_count"],
        "candidate_count": progress["candidate_count"],
    }


def _run_id() -> str:
    return f"run_{secrets.token_hex(16)}"


def _base_request(request: ReconciliationRequest) -> dict[str, Any]:
    value = json.loads(canonical_request_json(request))
    value.pop("assistant_proposal_id", None)
    return value


def _fresh_context(
    request: ReconciliationRequest,
    *,
    machine_builder: Any | None = None,
    census_builder: Any | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from cc.core.ecosystem import reconciliation as coordinator

    selections = {
        project.path: list(project.components) for project in request.projects
    }
    machine = (machine_builder or coordinator._default_machine_builder)()
    try:
        projects = coordinator._validated_projects(
            (census_builder or coordinator._default_census_builder)(
                roots=request.roots,
                selections=selections,
                detail=True,
            )
        )
        coordinator._validate_requested_authority(request, machine, projects)
    except Exception as exc:
        if type(exc).__name__ == "ReconciliationError":
            raise
        raise _reconciliation_error(
            "assistant-inspection-failed",
            "The selected projects could not be inspected safely for Claude Code preparation.",
            exit_code=2,
        ) from exc
    if coordinator._assessment_result(machine, projects) == "blocked":
        raise _reconciliation_error(
            "assistant-machine-blocked",
            "This Mac is not ready for bounded Claude Code preparation. Resolve the machine blocker and assess again.",
        )
    return machine, projects


def _component(project: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    matches = [
        item
        for item in project.get("components", [])
        if isinstance(item, Mapping) and item.get("component") == name
    ]
    if len(matches) != 1:
        raise _reconciliation_error(
            "assistant-candidate-unavailable",
            "A selected project component has no unambiguous bounded candidate.",
            exit_code=2,
        )
    return matches[0]


def _eligible_recipe_ids(
    project: Mapping[str, Any], component: str, assessment: Mapping[str, Any]
) -> list[str]:
    from cc.core.ecosystem.reconciliation_recipes import DEFAULT_RECIPE_REGISTRY

    if assessment.get("state") != ComponentRoute.CUSTOMIZED_GUIDED_ROUTE.value:
        return []
    offered: list[str] = []
    if component == "claude":
        for recipe_id in (
            _ASSISTANT_CLAUDE_RECIPE,
            _STANDARD_CLAUDE_RECIPE,
        ):
            try:
                DEFAULT_RECIPE_REGISTRY.require(
                    recipe_id,
                    component=component,
                    route=ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
                    root=Path(str(project["path"])),
                    assessment=assessment,
                    dossier=project.get("dossier") or {},
                )
            except Exception:
                continue
            offered.append(recipe_id)
    for option in assessment.get("recipe_options", []):
        if not isinstance(option, Mapping):
            continue
        recipe_id = option.get("recipe_id")
        if not isinstance(recipe_id, str) or recipe_id in offered:
            continue
        try:
            DEFAULT_RECIPE_REGISTRY.require(
                recipe_id,
                component=component,
                route=ComponentRoute.CUSTOMIZED_GUIDED_ROUTE,
                root=Path(str(project["path"])),
                assessment=assessment,
                dossier=project.get("dossier") or {},
            )
        except Exception:
            continue
        offered.append(recipe_id)
    return offered


def _candidate_catalog(
    request: ReconciliationRequest,
    projects: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_path = {str(project["path"]): project for project in projects}
    candidates: list[dict[str, Any]] = []
    packet_projects: list[dict[str, Any]] = []
    for selection in request.projects:
        project = by_path[selection.path]
        project_ref = f"project_{secrets.token_hex(16)}"
        packet_components: list[dict[str, Any]] = []
        for component in selection.components:
            if component in selection.recipe_ids:
                continue
            assessment = _component(project, component)
            if assessment.get("state") != ComponentRoute.CUSTOMIZED_GUIDED_ROUTE.value:
                continue
            recipe_ids = _eligible_recipe_ids(project, component, assessment)
            if not recipe_ids:
                raise _reconciliation_error(
                    "assistant-candidate-unavailable",
                    "A customized selected component has no bounded Python-authored repair candidate. It was left unchanged.",
                )
            option_ids: list[str] = []
            for recipe_id in recipe_ids:
                candidate_id = "candidate_" + secrets.token_hex(32)
                option_ids.append(candidate_id)
                candidates.append(
                    {
                        "candidate_id": candidate_id,
                        "project_ref": project_ref,
                        "project": selection.path,
                        "component": component,
                        "recipe_id": recipe_id,
                        "inspection_id": str(project.get("inspection_id", "")),
                    }
                )
            packet_components.append(
                {
                    "component": component,
                    "candidate_ids": option_ids,
                    "evidence_codes": ["customized-setup-present"],
                }
            )
        if packet_components:
            packet_projects.append(
                {"project_ref": project_ref, "components": packet_components}
            )
    if not candidates:
        raise _reconciliation_error(
            "assistant-not-required",
            "The selected projects do not require Claude Code preparation. Use the standard plan instead.",
            exit_code=2,
        )
    packet = {
        "schema_version": "1.0",
        "task": "select-bounded-project-reconciliation-candidates",
        "projects": packet_projects,
        "rules": {
            "select_exactly_one_candidate_per_component": True,
            "author_commands_paths_content_patches_operations": False,
        },
    }
    return candidates, packet


def build_assistant_prepare_report(
    request: ReconciliationRequest,
    *,
    state_root: Path | None = None,
    now: datetime | None = None,
    machine_builder: Any | None = None,
    census_builder: Any | None = None,
) -> dict[str, Any]:
    """Create one private, expiring, content-free Claude selection job."""
    if request.assistant_proposal_id is not None:
        raise _reconciliation_error(
            "invalid-assistant-request",
            "Start Claude Code preparation from the original project selection, not an existing proposal.",
            exit_code=2,
        )
    _, projects = _fresh_context(
        request,
        machine_builder=machine_builder,
        census_builder=census_builder,
    )
    candidates, packet = _candidate_catalog(request, projects)
    selected_projects = [project.path for project in request.projects]
    try:
        session = create_session(
            base_request=_base_request(request),
            packet=packet,
            candidates=candidates,
            selected_projects=selected_projects,
            policy_fingerprint=_POLICY_FINGERPRINT,
            root=state_root,
            now=now,
        )
    except AssistantStoreError as exc:
        raise _reconciliation_error(
            "assistant-store-error",
            "The private Claude Code preparation session could not be created safely.",
            exit_code=2,
        ) from exc
    progress = load_progress(session["session_id"], root=state_root, now=now)
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "assistant-prepare",
        "result": "ready",
        "run_id": _run_id(),
        "generated_at": _timestamp(now),
        "session_id": session["session_id"],
        "expires_at": session["expires_at"],
        "selected_projects": selected_projects,
        "progress": _progress_report(progress, now=now),
        "next_actions": [
            "Claude Code will choose only from Python-authored candidates. Nothing changes until you review and apply the resulting Python plan."
        ],
    }


def _resolved_claude_candidate() -> str | None:
    """Resolve the `claude` executable with the closed registry authoritative
    over the ambient PATH, consulting PATH only when the registry has no
    answer.

    The Finding B defect (STRIDE, Tampering) was that a PATH-order-dependent
    lookup (`shutil.which`) ran *first* and could therefore preempt a
    legitimate, trusted install location -- an attacker who could influence
    this process's PATH before it ran could steer resolution to a binary of
    their choosing even when a real `claude` was already installed at a known
    location. The defect was the ordering, not the mere existence of a PATH
    fallback: disabling PATH outright (as the first fix did) left any real
    user whose `claude` install is not one of `core/executables.py`'s known
    absolute locations -- e.g. an install directory outside that closed
    registry, or a sandboxed/non-standard `$HOME` -- with no way to resolve
    Claude Code at all.

    Resolution therefore checks `core/executables.py`'s closed registry of
    known, absolute install locations first (the same registry this codebase
    already uses for `gh`, `copilot`, `codex`, and `node`), and only falls
    back to the ambient PATH when the registry yields nothing. A registry hit
    can never be preempted by PATH. The `CC_ASSISTANT_CLAUDE_PATH` operator
    override, checked before this function runs, remains the highest-priority
    way to point at a `claude` install outside both of these sources. Every
    candidate, from any source, still passes through the ownership/permission
    checks in `_supported_claude_path` below before it may be executed.
    """
    from_registry = resolve_executable("claude", which=lambda _command: None)
    if from_registry is not None:
        return str(from_registry)
    from_path = resolve_executable("claude")
    return str(from_path) if from_path is not None else None


def _supported_claude_path(explicit: Path | None = None) -> Path:
    raw_value = (
        str(explicit)
        if explicit is not None
        else os.environ.get("CC_ASSISTANT_CLAUDE_PATH") or _resolved_claude_candidate()
    )
    if not raw_value:
        raise _reconciliation_error(
            "claude-code-unavailable",
            "Claude Code is not available from a supported executable path.",
        )
    try:
        resolved = Path(raw_value).expanduser().resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise _reconciliation_error(
            "claude-code-unavailable",
            "Claude Code is not available from a supported executable path.",
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid not in {0, os.geteuid()}
        or stat.S_IMODE(metadata.st_mode) & 0o022
        or not os.access(resolved, os.X_OK)
    ):
        raise _reconciliation_error(
            "claude-code-unsafe",
            "The Claude Code executable path is not a protected executable file.",
        )
    return resolved


def _safe_environment(*, test_mode: bool = False) -> dict[str, str]:
    allowed = {
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "PATH",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
        "CLAUDE_CONFIG_DIR",
    }
    if test_mode:
        allowed.update(
            name for name in os.environ if name.startswith("FAKE_CLAUDE_")
        )
    environment = {
        name: value for name, value in os.environ.items() if name in allowed
    }
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        value = environment.get(name)
        if not value:
            continue
        try:
            parsed = urlsplit(value if "://" in value else f"//{value}")
            has_credentials = (
                parsed.username is not None or parsed.password is not None
            )
        except ValueError:
            has_credentials = True
        if has_credentials:
            environment.pop(name, None)
    return environment


def _output_schema(session: Mapping[str, Any]) -> dict[str, Any]:
    candidates = session["candidates"]
    groups = {
        (str(item["project_ref"]), str(item["component"])) for item in candidates
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["selections"],
        "properties": {
            "selections": {
                "type": "array",
                "minItems": len(groups),
                "maxItems": len(groups),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["candidate_id"],
                    "properties": {
                        "candidate_id": {
                            "type": "string",
                            "enum": [str(item["candidate_id"]) for item in candidates],
                        }
                    },
                },
            }
        },
    }


def _prompt(session: Mapping[str, Any]) -> bytes:
    return json.dumps(
        {
            "instruction": (
                "Select exactly one offered candidate for every component group. "
                "Return only the required structured output. Do not author or infer "
                "commands, paths, content, patches, operations, or guidance."
            ),
            "packet": session["packet"],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _limit_child_output() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (_MAX_OUTPUT_BYTES, _MAX_OUTPUT_BYTES))


def _invoke_claude(
    session: Mapping[str, Any],
    *,
    claude_path: Path | None = None,
    timeout_seconds: int = _RUN_TIMEOUT_SECONDS,
    state_root: Path | None = None,
    heartbeat: Callable[[], None] | None = None,
) -> bytes:
    executable = _supported_claude_path(claude_path)
    directory = session_directory(str(session["session_id"]), state_root)
    working_directory = directory / "work"
    working_directory.mkdir(mode=0o700, exist_ok=True)
    working_metadata = working_directory.lstat()
    if (
        not stat.S_ISDIR(working_metadata.st_mode)
        or stat.S_ISLNK(working_metadata.st_mode)
        or working_metadata.st_uid != os.geteuid()
        or stat.S_IMODE(working_metadata.st_mode) & 0o077
    ):
        raise _reconciliation_error(
            "assistant-workspace-unsafe",
            "The private Claude Code working directory is unsafe.",
            exit_code=2,
        )
    schema = json.dumps(_output_schema(session), sort_keys=True, separators=(",", ":"))
    command = [
        str(executable),
        "--safe-mode",
        "--tools",
        "",
        "--permission-mode",
        "plan",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--no-chrome",
        "--print",
        "--input-format",
        "text",
        "--output-format",
        "json",
        "--json-schema",
        schema,
    ]
    stdout_path = directory / ".claude.stdout"
    stderr_path = directory / ".claude.stderr"
    for path in (stdout_path, stderr_path):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise _reconciliation_error(
                "assistant-output-unsafe",
                "The private Claude Code output area is unsafe.",
                exit_code=2,
            ) from exc
    stdout_fd = -1
    stderr_fd = -1
    try:
        stdout_fd = os.open(
            stdout_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        stderr_fd = os.open(
            stderr_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=stdout_fd,
            stderr=stderr_fd,
            cwd=working_directory,
            env=_safe_environment(
                test_mode=os.environ.get("CC_ASSISTANT_TEST_MODE") == "1"
            ),
            start_new_session=True,
            preexec_fn=_limit_child_output,
        )
        try:
            if process.stdin is None:
                raise OSError("Claude Code stdin is unavailable")
            process.stdin.write(_prompt(session))
            process.stdin.close()
            deadline = time.monotonic() + timeout_seconds
            while process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                try:
                    process.wait(timeout=min(2, remaining))
                except subprocess.TimeoutExpired:
                    if heartbeat is not None:
                        try:
                            heartbeat()
                        except Exception:
                            # Progress is observational, never assistant authority.
                            # If its sidecar becomes unavailable, let the bounded
                            # child finish and allow status to report stale evidence.
                            pass
        except subprocess.TimeoutExpired as exc:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            raise _reconciliation_error(
                "assistant-timeout",
                "Claude Code preparation timed out. No project was changed.",
            ) from exc
        if process.returncode != 0:
            raise _reconciliation_error(
                "assistant-run-failed",
                "Claude Code did not return a usable bounded proposal. No project was changed.",
            )
        if stdout_path.stat().st_size > _MAX_OUTPUT_BYTES:
            raise OSError("oversized")
        return stdout_path.read_bytes()
    except OSError as exc:
        raise _reconciliation_error(
            "assistant-output-invalid",
            "Claude Code returned an unreadable or oversized proposal. No project was changed.",
        ) from exc
    finally:
        if stdout_fd >= 0:
            os.close(stdout_fd)
        if stderr_fd >= 0:
            os.close(stderr_fd)
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)


def _reject_constant(value: str) -> Any:
    raise ValueError(f"unsupported JSON constant: {value}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bounded_json(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    nodes = count if count is not None else [0]
    nodes[0] += 1
    if depth > _MAX_JSON_DEPTH or nodes[0] > _MAX_JSON_NODES:
        raise ValueError("JSON structure exceeds the bounded assistant contract")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON keys must be strings")
            _bounded_json(item, depth=depth + 1, count=nodes)
    elif isinstance(value, list):
        for item in value:
            _bounded_json(item, depth=depth + 1, count=nodes)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("unsupported JSON value")


def _contains_prohibited_assistant_key(value: Any) -> bool:
    if isinstance(value, dict):
        if any(key in _PROHIBITED_ASSISTANT_KEYS for key in value):
            return True
        return any(_contains_prohibited_assistant_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_prohibited_assistant_key(item) for item in value)
    return False


def _validated_selections(
    output: bytes, session: Mapping[str, Any]
) -> list[dict[str, str]]:
    try:
        if not output or len(output) > _MAX_OUTPUT_BYTES:
            raise ValueError("empty or oversized")
        text = output.decode("utf-8", errors="strict")
        wrapper = json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_constant=_reject_constant,
        )
        _bounded_json(wrapper)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise _reconciliation_error(
            "assistant-output-invalid",
            "Claude Code returned an incompatible proposal. No project was changed.",
        ) from exc
    if (
        not isinstance(wrapper, dict)
        or not isinstance(wrapper.get("structured_output"), dict)
        or wrapper.get("type") != "result"
        or wrapper.get("subtype") != "success"
        or wrapper.get("is_error") is not False
        or not set(wrapper) <= _SAFE_WRAPPER_KEYS
        or _contains_prohibited_assistant_key(
            {key: value for key, value in wrapper.items() if key != "structured_output"}
        )
    ):
        raise _reconciliation_error(
            "assistant-output-invalid",
            "Claude Code did not return the required structured proposal. No project was changed.",
        )
    payload = wrapper["structured_output"]
    if set(payload) != {"selections"} or not isinstance(payload["selections"], list):
        raise _reconciliation_error(
            "assistant-output-invalid",
            "Claude Code returned fields outside the bounded proposal contract. No project was changed.",
        )
    raw_selections = payload["selections"]
    if any(not isinstance(item, dict) or set(item) != {"candidate_id"} for item in raw_selections):
        raise _reconciliation_error(
            "assistant-output-invalid",
            "Claude Code returned fields outside the bounded proposal contract. No project was changed.",
        )
    offered = {
        str(item["candidate_id"]): item for item in session["candidates"]
    }
    selected_ids = [item["candidate_id"] for item in raw_selections]
    if (
        any(not isinstance(item, str) or item not in offered for item in selected_ids)
        or len(selected_ids) != len(set(selected_ids))
    ):
        raise _reconciliation_error(
            "assistant-selection-invalid",
            "Claude Code selected an unavailable or repeated candidate. No project was changed.",
        )
    selected_groups = {
        (str(offered[item]["project_ref"]), str(offered[item]["component"]))
        for item in selected_ids
    }
    required_groups = {
        (str(item["project_ref"]), str(item["component"]))
        for item in session["candidates"]
    }
    if selected_groups != required_groups or len(selected_ids) != len(required_groups):
        raise _reconciliation_error(
            "assistant-selection-incomplete",
            "Claude Code did not select exactly one bounded candidate for every component. No project was changed.",
        )
    return [{"candidate_id": str(item)} for item in selected_ids]


def run_assistant_session(
    session_id: str,
    *,
    state_root: Path | None = None,
    claude_path: Path | None = None,
    timeout_seconds: int = _RUN_TIMEOUT_SECONDS,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Claim and run one assistant job without touching any project."""
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise _reconciliation_error(
            "assistant-session-invalid",
            "The Claude Code preparation session is invalid.",
            exit_code=2,
        )
    try:
        session = claim_session(session_id, root=state_root)
    except (AssistantStoreError, Exception) as exc:
        if type(exc).__name__ == "ReconciliationError":
            raise
        raise _reconciliation_error(
            "assistant-session-unavailable",
            "The Claude Code preparation session is unavailable or already in use.",
        ) from exc
    try:
        record_progress(session_id, "claude-code-running", root=state_root)
        if progress_callback is not None:
            project_count = len(session["selected_projects"])
            progress_callback(
                f"Claude Code preparation started for {project_count} "
                f"{'project' if project_count == 1 else 'projects'}."
            )
        output = _invoke_claude(
            session,
            claude_path=claude_path,
            timeout_seconds=timeout_seconds,
            state_root=state_root,
            heartbeat=lambda: record_progress(
                session_id, "claude-code-running", root=state_root
            ),
        )
        record_progress(session_id, "python-validating-selections", root=state_root)
        if progress_callback is not None:
            progress_callback("Python is validating Claude Code's bounded selections.")
        selections = _validated_selections(output, session)
        completed = complete_session(session_id, selections, root=state_root)
        progress = record_progress(
            session_id, "python-validating-plan", root=state_root
        )
        if progress_callback is not None:
            progress_callback("Python is rebuilding the exact project plan.")
    except Exception as exc:
        failure_code = getattr(exc, "code", None) or "assistant-run-rejected"
        try:
            complete_session(
                session_id,
                [],
                root=state_root,
                failure_code=failure_code,
            )
        except Exception:
            pass
        try:
            record_progress(
                session_id,
                "blocked",
                root=state_root,
                failure_code=failure_code,
            )
        except Exception:
            pass
        if type(exc).__name__ == "ReconciliationError":
            raise
        raise _reconciliation_error(
            "assistant-run-failed",
            "Claude Code preparation failed safely. No project was changed.",
        ) from exc
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "assistant-run",
        "result": "ready",
        "run_id": _run_id(),
        "generated_at": _timestamp(),
        "session_id": session_id,
        "selected_projects": completed["selected_projects"],
        "progress": _progress_report(progress),
        "detail": "Claude Code returned bounded selections for Python validation. No project was changed.",
        "next_actions": ["Return to Control Tower to review the exact Python plan."],
    }


def _resolved_request(session: Mapping[str, Any]) -> tuple[ReconciliationRequest, dict[str, list[str]]]:
    base = json.loads(json.dumps(session["base_request"], sort_keys=True))
    candidates = {
        str(item["candidate_id"]): item for item in session["candidates"]
    }
    selected_ids = [str(item["candidate_id"]) for item in session["selections"]]
    project_records = {
        str(item["path"]): item for item in base.get("projects", [])
    }
    owned: dict[str, list[str]] = {}
    for candidate_id in selected_ids:
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise _reconciliation_error(
                "assistant-proposal-invalid",
                "The stored Claude Code selection is no longer available.",
                exit_code=2,
            )
        path = str(candidate["project"])
        component = str(candidate["component"])
        recipe_id = str(candidate["recipe_id"])
        project = project_records.get(path)
        if project is None or component not in project.get("components", []):
            raise _reconciliation_error(
                "assistant-proposal-invalid",
                "The stored Claude Code selection does not match the project request.",
                exit_code=2,
            )
        recipe_ids = project.setdefault("recipe_ids", {})
        if component in recipe_ids:
            raise _reconciliation_error(
                "assistant-authority-overlap",
                "A Claude Code proposal cannot replace an explicit automatic recipe choice.",
                exit_code=2,
            )
        recipe_ids[component] = recipe_id
        owned.setdefault(path, []).append(component)
    return parse_reconciliation_request(base), owned


def _proposal_for_session(
    session: Mapping[str, Any],
    *,
    state_root: Path | None = None,
    now: datetime | None = None,
    plan_preparer: Any | None = None,
) -> dict[str, Any]:
    if session["state"] == "proposed" and session.get("proposal_id"):
        record_progress(
            str(session["session_id"]), "ready", root=state_root, now=now
        )
        return load_proposal(str(session["proposal_id"]), root=state_root, now=now)
    if session["state"] != "completed":
        raise _reconciliation_error(
            "assistant-session-incomplete",
            "Claude Code preparation is not complete.",
        )
    resolved, owned = _resolved_request(session)
    from cc.core.ecosystem.reconciliation import prepare_reconciliation

    session_id = str(session["session_id"])
    record_progress(session_id, "python-validating-plan", root=state_root, now=now)
    try:
        prepared = (plan_preparer or prepare_reconciliation)(resolved)
        proposal = issue_proposal(
            session_id,
            resolved_request=resolved.as_dict(),
            owned_components=owned,
            plans_fingerprint=fingerprint(prepared.public_plans),
            root=state_root,
            now=now,
        )
        record_progress(session_id, "ready", root=state_root, now=now)
        return proposal
    except Exception as exc:
        try:
            record_progress(
                session_id,
                "blocked",
                root=state_root,
                failure_code=(getattr(exc, "code", None) or "assistant-plan-invalid"),
                now=now,
            )
        except Exception:
            pass
        raise


def build_assistant_status_report(
    session_id: str,
    *,
    state_root: Path | None = None,
    now: datetime | None = None,
    plan_preparer: Any | None = None,
) -> dict[str, Any]:
    """Return running, rejected, or Python-validated proposal state."""
    if not isinstance(session_id, str) or _SESSION_ID.fullmatch(session_id) is None:
        raise _reconciliation_error(
            "assistant-session-invalid",
            "The Claude Code preparation session is invalid.",
            exit_code=2,
        )
    try:
        session = load_session(session_id, root=state_root, now=now)
        progress = load_progress(session_id, root=state_root, now=now)
        result = "running"
        proposal_id: str | None = None
        detail = "Claude Code is preparing bounded selections. Nothing has changed."
        next_actions = ["Keep Control Tower open while preparation finishes."]
        if session["state"] == "rejected" or progress["stage"] == "blocked":
            result = "blocked"
            detail = "Preparation stopped safely before Python could issue a valid plan. No project was changed."
            next_actions = ["Start project preparation again when Claude Code is available."]
        elif session["state"] in {"completed", "proposed"}:
            proposal = _proposal_for_session(
                session,
                state_root=state_root,
                now=now,
                plan_preparer=plan_preparer,
            )
            proposal_id = str(proposal["proposal_id"])
            progress = load_progress(session_id, root=state_root, now=now)
            result = "ready"
            detail = "Python validated Claude Code's bounded selections. The exact project plan is ready for review."
            next_actions = ["Review the exact Python plan before applying any project change."]
    except (AssistantNotFound, AssistantExpired, AssistantBindingMismatch, AssistantAlreadyUsed) as exc:
        raise _reconciliation_error(
            "assistant-session-unavailable",
            "The Claude Code preparation session is unavailable, expired, or failed validation. Start again.",
        ) from exc
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "phase": "assistant-status",
        "result": result,
        "run_id": _run_id(),
        "generated_at": _timestamp(now),
        "session_id": session_id,
        "proposal_id": proposal_id,
        "selected_projects": session["selected_projects"],
        "progress": _progress_report(progress, now=now),
        "detail": detail,
        "next_actions": next_actions,
    }


def resolve_assistant_request(
    request: ReconciliationRequest,
    *,
    state_root: Path | None = None,
) -> tuple[ReconciliationRequest, dict[str, Any]]:
    """Resolve one opaque proposal while preserving disjoint recipe authority."""
    proposal_id = request.assistant_proposal_id
    if not isinstance(proposal_id, str) or _PROPOSAL_ID.fullmatch(proposal_id) is None:
        raise _reconciliation_error(
            "assistant-proposal-invalid",
            "The Claude Code proposal identifier is invalid.",
            exit_code=2,
        )
    try:
        proposal = load_proposal(proposal_id, root=state_root)
    except AssistantStoreError as exc:
        raise _reconciliation_error(
            "assistant-proposal-unavailable",
            "The Claude Code proposal is unavailable, expired, or failed validation. Start preparation again.",
        ) from exc
    base = _base_request(request)
    if (
        proposal.get("policy_fingerprint") != _POLICY_FINGERPRINT
        or proposal.get("base_request") != base
        or proposal.get("request_fingerprint") != fingerprint(base)
    ):
        raise _reconciliation_error(
            "assistant-proposal-mismatch",
            "The Claude Code proposal does not match this exact project selection. Start preparation again.",
            exit_code=2,
        )
    try:
        resolved = parse_reconciliation_request(proposal["resolved_request"])
    except Exception as exc:
        raise _reconciliation_error(
            "assistant-proposal-invalid",
            "The Claude Code proposal contains an invalid resolved request.",
            exit_code=2,
        ) from exc
    base_projects = {project.path: project for project in request.projects}
    resolved_projects = {project.path: project for project in resolved.projects}
    owned = proposal.get("owned_components")
    if (
        resolved.roots != request.roots
        or set(resolved_projects) != set(base_projects)
        or not isinstance(owned, Mapping)
    ):
        raise _reconciliation_error(
            "assistant-proposal-mismatch",
            "The Claude Code proposal changed the selected project authority.",
            exit_code=2,
        )
    for path, base_project in base_projects.items():
        resolved_project = resolved_projects[path]
        owned_components = owned.get(path, [])
        if (
            resolved_project.components != base_project.components
            or not isinstance(owned_components, list)
            or len(owned_components) != len(set(owned_components))
            or any(component not in base_project.components for component in owned_components)
        ):
            raise _reconciliation_error(
                "assistant-proposal-mismatch",
                "The Claude Code proposal changed the selected component authority.",
                exit_code=2,
            )
        for component, recipe_id in base_project.recipe_ids.items():
            if (
                component in owned_components
                or resolved_project.recipe_ids.get(component) != recipe_id
            ):
                raise _reconciliation_error(
                    "assistant-authority-overlap",
                    "A Claude Code proposal cannot replace an explicit automatic recipe choice.",
                    exit_code=2,
                )
        added = set(resolved_project.recipe_ids) - set(base_project.recipe_ids)
        if added != set(owned_components):
            raise _reconciliation_error(
                "assistant-proposal-mismatch",
                "The Claude Code proposal added recipe authority outside its bounded components.",
                exit_code=2,
            )
    return resolved, proposal


__all__ = [
    "build_assistant_prepare_report",
    "build_assistant_status_report",
    "resolve_assistant_request",
    "run_assistant_session",
]
