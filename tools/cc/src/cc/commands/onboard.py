"""Fail-closed repository discovery and provisioning for desktop onboarding."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

import typer
import yaml

from cc.commands.doctor import build_doctor_report
from cc.commands.resolve import build_resolve_report
from cc.commands.update import execute_update
from cc.core import authstore, keychain
from cc.core.config import load_machine_config, resolve_key
from cc.core.config_paths import machine_config_path
from cc.core.ecosystem import mirror
from cc.core.ecosystem.manifest import (
    ManifestError,
    load_layers,
    normalize_layer_product,
    validate_layers,
)
from cc.core.ecosystem.repository_scope import (
    repository_identity as _repository_identity,
)
from cc.core.ecosystem.ssh_identity import ensure_machine_ssh_identity
from cc.core.executables import resolve_executable
from cc.core.write_guard import assert_write_is_isolated

SCHEMA_VERSION = "2.0"
# G-5 (task 208): bumped from "1.0" -- breaking. `ecosystemReport.layers`
# rows are now fully-required topology rows (or an explicit typed absence,
# `layers_state: "not-computed"`), never the skeletal four-field look-alike
# a raw `manifest["layers"]` row used to produce. See
# docs/01-architecture/cli-contract.md and schemas/onboard.schema.json in
# copilot-control-tower for the versioned contract.
COMPONENTS = ("knowledge", "cli", "claude", "codex")
PRODUCTS = ("claude", "codex")
LEGACY_FOUNDATION_REFS: dict[str, str] = {
    "knowledge": "^0.1.0",
    "cli": "^0.3.0",
}
# Plain-language, non-technical labels for the CLI/Copilot components -- used
# only inside user-facing `detail`/`title` strings. `str.title()` would
# render "cli" as "Cli"; every other component title-cases correctly.
_COMPONENT_LABELS: dict[str, str] = {
    "cli": "CLI",
    "claude": "Claude",
    "codex": "Codex",
    "knowledge": "Knowledge",
}
# Supply-chain roots are compiled into the signed cc distribution. They are
# deliberately not read from the environment, the Admin handoff, or a layer
# being verified (all three would let the artifact choose its own authority).
# Release engineering populates these tuples only after the corresponding
# public foundation starts publishing commits/tags signed by the real keys.
FOUNDATION_ALLOWED_SIGNERS: dict[str, tuple[str, ...]] = {
    "knowledge": (),
    "cli": (),
    "claude": ("SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo",),
    "codex": ("SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo",),
}
Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _component_label(component: str) -> str:
    return _COMPONENT_LABELS.get(component, component.title())


def _decline_detail(component: str) -> str:
    """The cost of leaving an `adoptable` space out of this run (B1 ask/decline).

    Rendered verbatim under a cleared question row; never invented by the app
    (invariant #1). Only meaningful for `adoptable` -- every other package
    state either has nothing to decline or isn't offered as a question.
    """
    return (
        f"Without this, {_component_label(component)} Copilot can't be set up "
        "on this Mac. You can include it later."
    )


@dataclass(frozen=True)
class Probe:
    state: str
    visibility: str | None
    detail: str


@dataclass(frozen=True)
class PackageProbe:
    state: str
    detail: str


@dataclass(frozen=True)
class HistoryClassification:
    """The closed result of comparing a visible checkout's Git history to its
    expected GitHub origin (G-1). Exactly one of nine states is returned,
    never anything invented in between, and every field is proven by an
    actual `git`/`gh` fact -- never inferred from "the tree is clean and the
    SHAs differ".

    ``state`` is the canonical, closed classification (one of: ``exact``,
    ``fast-forwardable``, ``dirty``, ``ahead-only``,
    ``parentless-snapshot-match``, ``divergent-identical-tree``,
    ``divergent-different-content``, ``wrong-origin``, ``unreadable``).
    ``sync_state``/``action``/``detail`` are the user-facing fields this
    collapses onto in the topology report.

    ``parentless-snapshot-match`` (task 209/G-7) covers foundation snapshot
    releases (e.g. `foundation-snapshot-release.py`), which deliberately
    publish PARENTLESS pinned commits/tags -- the pin's commit is never an
    ancestor or descendant of any working branch, so ordinary ancestry
    comparison can never align it. Without this state, a checkout that
    already matches such a pin's active content byte-for-byte would be
    misclassified ``divergent-identical-tree``/``review`` forever, with no
    Git action the owner could ever take to clear it. It is deliberately
    narrow: only a PARENTLESS pinned target whose full tree, or configured
    ``source.subpath`` when present, is byte-identical to the same content in
    a clean working tree qualifies. This lets a Foundation authoring checkout
    retain release tooling outside the content Copilot actually consumes
    without fabricating a divergence. A non-parentless pin with matching
    content (a real, continuously-evolving repository, where history alignment
    genuinely remains possible) still requires ordinary history alignment,
    and any difference inside the active content still classifies
    ``divergent-different-content``/``review``.

    This is the single source of truth for "is it safe to touch this
    checkout, and how" -- both the plan/report path
    (``_topology_report_layers``) and the apply path
    (``_apply_visible_topology``, and its task-205 postcondition assertions)
    must agree with exactly this function. Only ``fast-forwardable`` may ever
    promise "a clean fast-forward is available", and only because
    `git merge-base --is-ancestor` proved it -- every other non-``exact``
    state routes to the owner (``action == "review"``) and is never
    auto-repaired (never-destroy).
    """

    state: str
    sync_state: str
    action: str
    detail: str


@dataclass(frozen=True)
class ManifestAdoption:
    state: str
    action: str
    detail: str
    source: Path | None
    destination: Path
    payload: dict[str, Any] | None

    def as_item(self) -> dict[str, Any]:
        return {
            "id": "layer-manifest",
            "scope": "machine",
            "title": "How your copilots fit together",
            "state": self.state,
            "action": self.action,
            "detail": self.detail,
            "source_path": str(self.source) if self.source else None,
            "destination_path": str(self.destination),
            # `reversible: true` means one specific thing everywhere else in
            # this module (see `_personal_inventory`/`_ssh_inventory`):
            # nothing has been written yet, so declining costs nothing, and
            # `adopt_existing` is the token that gates whether the write
            # happens at all. `migrate`/`repair` do not qualify -- a
            # recognized *existing* manifest is being merged and overwritten
            # (with a content-addressed backup, which is a safety net, not a
            # consent gate), and `_apply_manifest_adoption` below has never
            # been gated on `adopt_existing`. Marking this `True` rendered a
            # checkbox the app let the person clear while the write happened
            # anyway -- a false choice (spec: adopt-and-honesty-copy-spec.md
            # §1.5). This is also not user-decidable content: "how your
            # copilots fit together" is infrastructure only the CLI can
            # reason about, so per invariant #5 it is auto-acted on rather
            # than asked about, the same way `create` (a brand-new manifest)
            # already was. `False` here is what keeps the row out of the
            # question screen's ask list entirely, instead of presenting a
            # decision that was never real.
            "reversible": False,
        }


def _safe_repository_reference(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        return False
    if any(marker in value for marker in ("ghp_", "gho_", "ghu_", "github_pat_")):
        return False
    if value.startswith(("http://", "https://")):
        parsed = urlsplit(value)
        return parsed.username is None and parsed.password is None
    return True


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if not args:
        return subprocess.CompletedProcess(args, 127, "", "No command was provided.")
    executable = resolve_executable(args[0])
    if executable is None:
        return subprocess.CompletedProcess(
            args, 127, "", f"{args[0]} is not installed."
        )
    resolved = str(executable)
    environment = None
    try:
        with executable.open("rb") as handle:
            first_line = handle.readline(256).decode("utf-8").strip()
    except (OSError, UnicodeDecodeError):
        first_line = ""
    if first_line.startswith("#!/usr/bin/env "):
        try:
            shebang = shlex.split(first_line[2:])
        except ValueError:
            shebang = []
        runtime = next(
            (
                token
                for token in shebang[1:]
                if token != "-S" and not token.startswith("-")
            ),
            None,
        )
        if runtime:
            runtime_path = resolve_executable(runtime)
            if runtime_path is None:
                return subprocess.CompletedProcess(
                    args,
                    127,
                    "",
                    f"{runtime} runtime required by {args[0]} is not installed.",
                )
            environment = os.environ.copy()
            current_path = environment.get("PATH", "")
            environment["PATH"] = os.pathsep.join(
                part for part in (str(runtime_path.parent), current_path) if part
            )
    if Path(resolved).name == "gh":
        try:
            identity = authstore.read_identity()
            login = identity.get("login") if isinstance(identity, dict) else None
            service = resolve_key("auth.keychain_service")
            token = (
                keychain.get_secret(login, service=service)
                if login and service
                else None
            )
        except (RuntimeError, OSError):
            token = None
        if token:
            environment = environment or os.environ.copy()
            environment["GH_TOKEN"] = token
    return subprocess.run(
        (resolved, *args[1:]),
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )


def _probe(owner: str, name: str, *, run: Run) -> Probe:
    result = run(("gh", "api", f"repos/{owner}/{name}"))
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
            private = payload["private"]
            if not isinstance(private, bool):
                raise ValueError("private is not boolean")
        except (json.JSONDecodeError, KeyError, ValueError):
            return Probe(
                "unknown", None, "GitHub returned an unreadable repository response."
            )
        if private:
            return Probe(
                "existing-private",
                "private",
                "You already have this space. I'll use it as it is.",
            )
        return Probe(
            "conflict-public",
            "public",
            "Something of yours is already using this name publicly, so I stopped. Nothing existing was changed.",
        )

    if "HTTP 404" in result.stderr:
        return Probe(
            "missing",
            None,
            "You don't have this space yet. I'll create it privately for you.",
        )
    return Probe(
        "unknown",
        None,
        "GitHub couldn't confirm this space right now, so I won't guess.",
    )


def _owner(*, run: Run) -> str:
    result = run(("gh", "api", "user", "--jq", ".login"))
    owner = result.stdout.strip()
    if result.returncode != 0 or not owner:
        raise RuntimeError(
            "GitHub could not confirm the authenticated personal account."
        )
    return owner


def _is_404(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and "HTTP 404" in result.stderr


def _decode_github_content(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
        encoded = payload["content"]
        if not isinstance(encoded, str):
            return None
        return base64.b64decode(encoded.replace("\n", "")).decode("utf-8")
    except (json.JSONDecodeError, KeyError, ValueError, UnicodeDecodeError):
        return None


def _valid_personal_manifest(content: str, component: str) -> bool:
    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    if not isinstance(payload, dict):
        return False
    package = payload.get("package")
    return bool(
        payload.get("schema_version") == "1.0"
        and isinstance(package, dict)
        and package.get("role") == "personal"
        and package.get("rank") == 10
        and package.get("product") == component
    )


def _probe_package(owner: str, name: str, component: str, *, run: Run) -> PackageProbe:
    """Classify an existing private repo without interpreting user content."""
    manifest = run(("gh", "api", f"repos/{owner}/{name}/contents/copilot.layer.yml"))
    if manifest.returncode == 0:
        content = _decode_github_content(manifest.stdout)
        if content is not None and _valid_personal_manifest(content, component):
            return PackageProbe(
                "ready", "Already set up. Everything in here will be kept."
            )
        # A marker file is present but not one we recognize. This MUST stay a
        # hard block, never an offer: writing over or beside an unfamiliar
        # marker would not be a purely additive change, unlike the
        # no-marker-at-all case below.
        return PackageProbe(
            "held",
            "I don't recognize how this space is set up, so I'll leave it exactly as it is.",
        )
    if not _is_404(manifest):
        return PackageProbe(
            "unknown",
            "GitHub couldn't confirm what's already set up in this space, so I won't guess.",
        )

    contents = run(("gh", "api", f"repos/{owner}/{name}/contents"))
    if _is_404(contents):
        # GitHub returns 404 for the root contents endpoint when a repository
        # has no commits. The repository itself was already confirmed private.
        return PackageProbe("empty", "Empty and ready. I'll set it up for you.")
    if contents.returncode != 0:
        # `package_state == "unknown"` wins the `package_detail or detail`
        # ordering in `_personal_inventory`/`personal_detail`, so an
        # otherwise-blocked plan surfaces exactly this sentence inline on
        # the Holding screen (`framedIfPresentable`), not just the
        # collapsed support block. It must carry the same closed vocabulary
        # as every other reachable string here (no `repo`/`repository`).
        return PackageProbe(
            "unknown",
            "GitHub couldn't confirm whether this space is empty, so I won't guess.",
        )
    try:
        root = json.loads(contents.stdout)
    except json.JSONDecodeError:
        return PackageProbe(
            "unknown",
            "GitHub's answer about what's in this space wasn't something I could read.",
        )
    if isinstance(root, list) and not root:
        return PackageProbe("empty", "Empty and ready. I'll set it up for you.")
    # Private, non-empty, no root marker at all: nothing to conflict with, so
    # this is an offer to include the person's own content, not a refusal.
    # Writing the marker later is purely additive (B1).
    return PackageProbe(
        "adoptable",
        "Your own content is already in here. I'll keep all of it and add a small note that says it belongs with your copilots.",
    )


def _personal_seed(component: str) -> str:
    return yaml.safe_dump(
        {
            "schema_version": "1.0",
            "package": {
                "role": "personal",
                "rank": 10,
                "product": component,
                "owner": "authenticated-user",
            },
            "dimensions": [],
        },
        sort_keys=False,
    )


def _seed_package(owner: str, name: str, component: str, *, run: Run) -> bool:
    encoded = base64.b64encode(_personal_seed(component).encode("utf-8")).decode(
        "ascii"
    )
    result = run(
        (
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{owner}/{name}/contents/copilot.layer.yml",
            "-f",
            "message=Initialize private personal Copilot layer",
            "-f",
            f"content={encoded}",
        )
    )
    return result.returncode == 0


def _row(
    component: str, owner: str, probe: Probe, package: PackageProbe | None
) -> dict[str, Any]:
    package_state = (
        package.state
        if package
        else ("missing" if probe.state == "missing" else "unknown")
    )
    package_action = (
        "seed"
        if package_state in {"missing", "empty"}
        else "none"
        if package_state == "ready"
        else "adopt"
        if package_state == "adoptable"
        else "blocked"
    )
    return {
        "component": component,
        "role": "personal",
        "unit": None,
        "owner": owner,
        "name": f"{component}-copilot-private",
        "visibility": probe.visibility,
        "state": probe.state,
        "action": "create"
        if probe.state == "missing"
        else (
            "none"
            if probe.state == "existing-private" and package_action != "blocked"
            else "blocked"
        ),
        "detail": probe.detail,
        "rank": 10,
        "package_state": package_state,
        "package_action": package_action,
        "package_detail": package.detail
        if package
        else "Will be set up right after this space is created.",
        "decline_detail": _decline_detail(component)
        if package_state == "adoptable"
        else "",
    }


def _report(
    owner: str, mode: str, rows: list[dict[str, Any]], result: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "scope": "personal",
        "owner": owner,
        "mode": mode,
        "result": result,
        "repositories": rows,
        "summary": {
            "existing": sum(row["state"] == "existing-private" for row in rows),
            "missing": sum(row["state"] == "missing" for row in rows),
            "created": sum(row["state"] == "created" for row in rows),
            "seeded": sum(row["package_state"] == "seeded" for row in rows),
            "held": sum(row["package_state"] == "held" for row in rows),
            "adoptable": sum(row["package_state"] == "adoptable" for row in rows),
            "blocked": sum(row["action"] == "blocked" for row in rows),
        },
    }


def build_personal_onboard_report(
    *,
    components: Sequence[str] = COMPONENTS,
    apply: bool = False,
    adopt_existing: Sequence[str] = (),
    run: Run = _run,
) -> dict[str, Any]:
    """Plan or apply personal repositories. Apply always repeats the full probe.

    `adopt_existing` is component-scoped consent (B1): a component in this
    set whose repository is `adoptable` (private, non-empty, no root marker)
    has its marker written on apply. Every other adoptable component is left
    exactly as it is -- an unlisted adoptable item is a no-op, never an
    implicit decline that changes what the CLI reports next time.
    """
    normalized = tuple(
        dict.fromkeys(component.strip().lower() for component in components)
    )
    invalid = [component for component in normalized if component not in COMPONENTS]
    if not normalized or invalid:
        raise ValueError(f"Unsupported components: {', '.join(invalid) or 'none'}")
    consent = {value.strip().lower() for value in adopt_existing if value.strip()}

    owner = _owner(run=run)
    rows = []
    for component in normalized:
        name = f"{component}-copilot-private"
        probe = _probe(owner, name, run=run)
        package = (
            _probe_package(owner, name, component, run=run)
            if probe.state == "existing-private"
            else None
        )
        rows.append(_row(component, owner, probe, package))
    blocked = any(row["action"] == "blocked" for row in rows)
    if blocked:
        return _report(owner, "apply" if apply else "plan", rows, "blocked")
    if not apply:
        needs_change = any(
            row["state"] == "missing" or row["package_state"] in {"empty", "adoptable"}
            for row in rows
        )
        return _report(
            owner, "plan", rows, "changes-required" if needs_change else "ready"
        )

    for row in rows:
        if row["state"] != "missing":
            continue
        created = run(
            (
                "gh",
                "api",
                "-X",
                "POST",
                "user/repos",
                "-f",
                f"name={row['name']}",
                "-F",
                "private=true",
                "-F",
                "auto_init=false",
                "-f",
                f"description=Private personal layer for {row['component'].title()} Copilot",
            )
        )
        if created.returncode == 0:
            row.update(
                state="created",
                visibility="private",
                action="none",
                detail="Created private repository.",
            )
            row["package_state"] = "empty"
        else:
            row.update(
                state="unknown",
                action="blocked",
                detail="GitHub did not confirm repository creation.",
            )
            return _report(owner, "apply", rows, "blocked")
    for row in rows:
        adopting = row["package_state"] == "adoptable" and row["component"] in consent
        if row["package_state"] != "empty" and not adopting:
            continue
        # `_seed_package` PUTs without a `sha`, so this write is additive: a
        # marker that appears between the probe above and this write makes
        # GitHub itself refuse the PUT rather than silently overwriting it.
        if _seed_package(owner, row["name"], row["component"], run=run):
            if adopting:
                row.update(
                    package_state="adopted",
                    package_action="none",
                    package_detail="Everything already in here will be kept, and it's now part of your copilots.",
                    # Consented and written: there is nothing left to decline.
                    decline_detail="",
                )
            else:
                row.update(
                    package_state="seeded",
                    package_action="none",
                    package_detail="Set up and ready.",
                )
        else:
            row.update(
                package_state="unknown",
                package_action="blocked",
                action="blocked",
                package_detail=(
                    f"GitHub didn't confirm the change to your "
                    f"{_component_label(row['component'])} Copilot space, so I "
                    "stopped. Nothing existing was changed."
                ),
            )
            return _report(owner, "apply", rows, "blocked")
    return _report(owner, "apply", rows, "applied")


def _github_file(owner: str, repo: str, path: str, *, run: Run) -> str:
    result = run(("gh", "api", f"repos/{owner}/{repo}/contents/{path}"))
    if result.returncode != 0:
        raise RuntimeError(f"GitHub could not read {owner}/{repo}/{path}.")
    content = _decode_github_content(result.stdout)
    if content is None:
        raise RuntimeError(f"GitHub returned an unreadable {path} handoff.")
    return content


def _load_handoff(org: str, products: Sequence[str], *, run: Run) -> dict[str, Any]:
    errors: list[str] = []
    for product in products:
        repo = f"{product}-copilot-internal"
        try:
            raw = _github_file(org, repo, "ecosystem.yml", run=run)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        try:
            handoff = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise RuntimeError(f"{org}/{repo}/ecosystem.yml is invalid YAML.") from exc
        configured = handoff.get("harness") if isinstance(handoff, dict) else None
        if not isinstance(handoff, dict) or handoff.get("schema_version") != "2.0":
            raise RuntimeError(
                f"{org}/{repo}/ecosystem.yml is not a supported v2 handoff."
            )
        if handoff.get("org") != org:
            raise RuntimeError(
                f"{org}/{repo}/ecosystem.yml names a different organization."
            )
        if not isinstance(configured, list) or any(
            value not in configured for value in products
        ):
            raise RuntimeError(
                "The organization handoff does not enable every requested Copilot product."
            )
        return handoff
    raise RuntimeError(
        errors[0] if errors else "No organization handoff repository was selected."
    )


def _discover_org(products: Sequence[str], *, run: Run) -> str:
    result = run(("gh", "api", "user/orgs", "--paginate"))
    if result.returncode != 0:
        raise RuntimeError(
            "GitHub could not list the organizations available to this account."
        )
    try:
        organizations = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub returned an unreadable organization list.") from exc
    matches: list[str] = []
    for item in organizations if isinstance(organizations, list) else []:
        login = item.get("login") if isinstance(item, dict) else None
        if not isinstance(login, str) or not login:
            continue
        try:
            _load_handoff(login, products, run=run)
        except RuntimeError:
            continue
        matches.append(login)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise RuntimeError(
            "No organization with a complete Copilot handoff was found for this account."
        )
    raise RuntimeError(
        "More than one organization has a Copilot handoff. Choose one with --org <name>."
    )


def _eligible_department_units(
    handoff: dict[str, Any], org: str, owner: str, *, run: Run
) -> tuple[str, ...]:
    """Return only handoff-declared departments this GitHub user belongs to.

    A department repository is never inferred from a local folder name. The
    organization handoff declares the bounded candidate set and GitHub team
    membership supplies the current entitlement proof.
    """
    units: list[str] = []
    for row in handoff.get("departments") or []:
        unit = row.get("unit") if isinstance(row, dict) else None
        if not isinstance(unit, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", unit):
            continue
        membership = run(("gh", "api", f"orgs/{org}/teams/{unit}/memberships/{owner}"))
        if membership.returncode != 0:
            continue
        try:
            payload = json.loads(membership.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("state") == "active":
            units.append(unit)
    return tuple(dict.fromkeys(units))


def _canonical_repository_names(department_units: Sequence[str] = ()) -> set[str]:
    names: set[str] = set()
    for component in COMPONENTS:
        names.update(
            {
                f"{component}-copilot",
                f"{component}-copilot-internal",
                f"{component}-copilot-private",
            }
        )
        names.update(f"{component}-copilot-{unit}" for unit in department_units)
    return names


def _infer_repository_root(department_units: Sequence[str] = ()) -> Path | None:
    """Infer one visible checkout folder from already approved local roots.

    Only the configured repository root and the immediate children of
    `projects.roots` are inspected. This keeps discovery bounded while still
    finding the common `/Sites/COPILOT/<component>` layout.
    """
    configured = resolve_key("paths.repositories_root")
    if configured:
        return Path(str(configured)).expanduser()
    roots = resolve_key("projects.roots")
    if isinstance(roots, str):
        roots = [roots]
    if not isinstance(roots, list):
        return None
    expected = _canonical_repository_names(department_units)
    scored: list[tuple[int, Path]] = []
    for raw in roots:
        if not isinstance(raw, str) or not raw:
            continue
        root = Path(raw).expanduser()
        candidates = [root]
        try:
            candidates.extend(path for path in root.iterdir() if path.is_dir())
        except OSError:
            pass
        for candidate in candidates:
            try:
                score = sum((candidate / name).is_dir() for name in expected)
            except OSError:
                score = 0
            if score:
                scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], len(item[1].parts), str(item[1])))
    best_score = scored[0][0]
    best = {path for score, path in scored if score == best_score}
    return next(iter(best)) if len(best) == 1 else None


def _repo_identity_from_layer(layer: dict[str, Any]) -> tuple[str, str] | None:
    identity = _repository_identity((layer.get("source") or {}).get("repo"))
    if not identity:
        return None
    owner, name = identity.split("/", 1)
    return owner, name


def _git_output(path: Path, *args: str, run: Run) -> subprocess.CompletedProcess[str]:
    return run(("git", "-C", str(path), *args))


def _classify_repository_history(
    local: Path, *, owner: str, name: str, source: dict[str, Any], run: Run
) -> HistoryClassification:
    """Classify `local`'s Git history against `owner/name`'s `source["ref"]`.

    Every branch is a fact proven by an actual `git` command; there is no
    "clean tree + different SHA implies fast-forward" shortcut anywhere in
    here (that was G-1). Ancestry is decided only by
    `git merge-base --is-ancestor`, which requires the target commit's object
    to exist locally -- so this fetches `source["repo"]`/`source["ref"]`
    into `local`'s object store (never into the working tree or an index)
    before ever comparing SHAs, mirroring how `_apply_visible_topology`'s
    `repair` branch already fetches before its `--ff-only` merge.
    """
    if not (local / ".git").is_dir():
        return HistoryClassification(
            "unreadable",
            "unreadable",
            "review",
            f"{local} exists but is not a Git repository. Nothing will be changed.",
        )

    origin = _git_output(local, "remote", "get-url", "origin", run=run)
    origin_identity = (
        _repository_identity(origin.stdout.strip()) if origin.returncode == 0 else None
    )
    expected_identity = f"{owner}/{name}".casefold() if owner and name else None
    if origin_identity != expected_identity:
        return HistoryClassification(
            "wrong-origin",
            "wrong-origin",
            "review",
            f"{local} points to a different GitHub repository. Nothing will be changed.",
        )

    head = _git_output(local, "rev-parse", "HEAD", run=run)
    status = _git_output(local, "status", "--porcelain", run=run)
    if head.returncode != 0 or status.returncode != 0:
        return HistoryClassification(
            "unreadable",
            "unreadable",
            "review",
            f"{local}'s Git history could not be read. Nothing will be changed.",
        )
    head_sha = head.stdout.strip()
    if status.stdout.strip():
        return HistoryClassification(
            "dirty",
            "local-changes",
            "review",
            f"Visible at {local}; local work will be preserved.",
        )

    ref = source.get("ref", "main")
    fetch = _git_output(local, "fetch", source.get("repo", ""), ref, run=run)
    if fetch.returncode != 0:
        return HistoryClassification(
            "unreadable",
            "unreadable",
            "review",
            f"Visible at {local}; GitHub currency could not be confirmed.",
        )
    # `FETCH_HEAD^{commit}` peels an annotated tag object down to the commit
    # it points at; a lightweight tag or branch/commit ref is already a
    # commit and passes through unchanged. Every downstream comparison in
    # this function (exact-match, merge-base ancestry, tree equality) -- and
    # the mirrored fetch in `_apply_visible_topology`'s `repair` branch --
    # must resolve `FETCH_HEAD` the same way, or a repository pinned exactly
    # at an annotated tag can never match ``target_sha`` (`rev-parse`, unlike
    # `merge`/`checkout`/`merge-base`, does not auto-peel tag objects).
    target = _git_output(local, "rev-parse", "FETCH_HEAD^{commit}", run=run)
    if target.returncode != 0:
        return HistoryClassification(
            "unreadable",
            "unreadable",
            "review",
            f"Visible at {local}; GitHub currency could not be confirmed.",
        )
    target_sha = target.stdout.strip()

    if head_sha == target_sha:
        return HistoryClassification(
            "exact",
            "current",
            "reuse",
            f"Visible at {local}; its checked-out revision matches GitHub.",
        )

    forward = _git_output(local, "merge-base", "--is-ancestor", head_sha, target_sha, run=run)
    if forward.returncode == 0:
        return HistoryClassification(
            "fast-forwardable",
            "behind",
            "repair",
            f"Visible at {local}; a clean fast-forward is available.",
        )

    backward = _git_output(local, "merge-base", "--is-ancestor", target_sha, head_sha, run=run)
    if backward.returncode == 0:
        return HistoryClassification(
            "ahead-only",
            "ahead",
            "review",
            f"Visible at {local}; local commits are not yet on GitHub and will be preserved, not overwritten.",
        )

    local_tree = _git_output(local, "rev-parse", "HEAD^{tree}", run=run)
    target_tree = _git_output(local, "rev-parse", f"{target_sha}^{{tree}}", run=run)
    full_tree_matches = (
        local_tree.returncode == 0
        and target_tree.returncode == 0
        and local_tree.stdout.strip()
        and local_tree.stdout.strip() == target_tree.stdout.strip()
    )
    active_subpath = source.get("subpath")
    has_active_subpath = isinstance(active_subpath, str) and bool(active_subpath)
    if full_tree_matches or has_active_subpath:
        # `target_sha^@` lists the target commit's parent SHA(s) (empty
        # output means it has none). A working tree that's already clean
        # (proven above) and byte-identical to a PARENTLESS pinned target's
        # active content genuinely *is* current for this layer -- only its
        # unrelated commit history or files outside `source.subpath` differ.
        # That is permanent and expected for a foundation snapshot release,
        # not a real divergence any owner action could resolve. See
        # `HistoryClassification`'s docstring (task 209/G-7, task 250).
        parents = _git_output(local, "rev-parse", f"{target_sha}^@", run=run)
        target_is_parentless = parents.returncode == 0 and not parents.stdout.strip()
        if target_is_parentless:
            if full_tree_matches:
                return HistoryClassification(
                    "parentless-snapshot-match",
                    "current",
                    "reuse",
                    f"Visible at {local}; content matches the pinned snapshot exactly (foundation snapshot releases are parentless by design, so only their unrelated commit history differs).",
                )
            local_content = _git_output(
                local, "rev-parse", f"{head_sha}:{active_subpath}", run=run
            )
            target_content = _git_output(
                local, "rev-parse", f"{target_sha}:{active_subpath}", run=run
            )
            if (
                local_content.returncode == 0
                and target_content.returncode == 0
                and local_content.stdout.strip()
                and local_content.stdout.strip() == target_content.stdout.strip()
            ):
                return HistoryClassification(
                    "parentless-snapshot-match",
                    "current",
                    "reuse",
                    f"Visible at {local}; the Copilot content this Mac uses matches the current release. Files outside that content are different and will be left alone.",
                )
    if full_tree_matches:
        return HistoryClassification(
            "divergent-identical-tree",
            "diverged-identical",
            "review",
            f"Visible at {local}; history has diverged from GitHub, but the content is identical -- only history differs.",
        )

    return HistoryClassification(
        "divergent-different-content",
        "diverged",
        "review",
        f"Visible at {local}; history has diverged from GitHub and the content differs. Nothing will be changed.",
    )


def _repository_permission(payload: dict[str, Any]) -> str:
    """Return GitHub's highest proven repository permission, fail-closed.

    GitHub's REST repository payload exposes calculated permission booleans.
    Setup uses this only as evidence for whether a future, separately gated
    authoring workflow could publish.  It never upgrades this setup workflow
    beyond download-only access.
    """
    permissions = payload.get("permissions")
    if not isinstance(permissions, dict):
        return "unknown"
    for key, label in (
        ("admin", "admin"),
        ("maintain", "maintain"),
        ("push", "write"),
        ("triage", "triage"),
        ("pull", "read"),
    ):
        if permissions.get(key) is True:
            return label
    return "unknown"


def _remote_repository_state(
    owner: str, name: str, *, run: Run
) -> tuple[str, str | None, str, bool]:
    result = run(("gh", "api", f"repos/{owner}/{name}"))
    if result.returncode != 0:
        return (
            ("missing", None, "unknown", False)
            if _is_404(result)
            else ("unknown", None, "unknown", False)
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return "unknown", None, "unknown", False
    if not isinstance(payload, dict):
        return "unknown", None, "unknown", False
    visibility = "private" if payload.get("private") is True else "public"
    permission = _repository_permission(payload)
    author_capable = permission in {"write", "maintain", "admin"}
    contents = run(("gh", "api", f"repos/{owner}/{name}/contents"))
    if _is_404(contents):
        return "empty", visibility, permission, author_capable
    return (
        ("ready", visibility, permission, author_capable)
        if contents.returncode == 0
        else ("unknown", visibility, permission, author_capable)
    )


def _topology_report_layers(
    manifest: dict[str, Any], *, run: Run, verified: bool = False
) -> list[dict[str, Any]]:
    """Return user-facing repository evidence for every expected layer."""
    rows: list[dict[str, Any]] = []
    for layer in manifest["layers"]:
        source = layer.get("source") or {}
        identity = _repo_identity_from_layer(layer)
        local_raw = source.get("path")
        local = Path(local_raw).expanduser() if isinstance(local_raw, str) else None
        if local is None:
            remote_state, visibility, permission, author_capable = (
                "not-checked",
                None,
                "unknown",
                False,
            )
            owner, name = identity or ("", "")
        elif identity is None:
            remote_state, visibility, permission, author_capable = (
                "unknown",
                None,
                "unknown",
                False,
            )
            owner, name = "", ""
        else:
            owner, name = identity
            remote = _remote_repository_state(owner, name, run=run)
            # Keep the long-standing two-field monkeypatch seam accepted by
            # contract/security tests while the production probe now returns
            # the additive authority evidence.
            if len(remote) == 2:
                remote_state, visibility = remote
                permission, author_capable = "unknown", False
            else:
                remote_state, visibility, permission, author_capable = remote

        local_state = "location-required" if local is None else "missing"
        sync_state = "not-checked"
        action = "choose-location" if local is None else "download"
        detail = "Choose the visible folder where your Copilot repositories belong."
        if local is not None and local.exists():
            classification = _classify_repository_history(
                local, owner=owner, name=name, source=source, run=run
            )
            local_state = (
                "conflict"
                if classification.state in {"wrong-origin", "unreadable"}
                else "visible"
            )
            sync_state = classification.sync_state
            action = classification.action
            detail = classification.detail
        elif local is not None:
            if remote_state == "missing" and layer["role"] != "personal":
                action = "review"
                detail = f"{owner}/{name} does not exist, so Control Tower will not invent this shared layer."
            elif remote_state == "empty" and layer["role"] == "department":
                action = "initialize"
                detail = f"Initialize the empty {owner}/{name} layer, then download it to {local}."
            elif remote_state == "missing" and layer["role"] == "personal":
                action = "create"
                detail = f"Create the private {owner}/{name} repository, then download it to {local}."
            elif remote_state in {"ready", "empty"}:
                action = "download"
                detail = f"Download {owner}/{name} to {local}."
            else:
                action = "review"
                detail = f"GitHub could not confirm {owner}/{name}; nothing will be changed."

        rows.append(
            {
                "id": layer["id"],
                "product": layer["product"],
                "role": layer["role"],
                "rank": layer["rank"],
                "unit": layer.get("unit"),
                "repository_owner": owner,
                "repository_name": name,
                "repository_visibility": visibility,
                "repository_permission": permission,
                "author_capable": author_capable,
                "setup_access": "download-only",
                "remote_state": remote_state,
                "local_path": str(local) if local else None,
                "local_state": local_state,
                "connection_state": (
                    "verified"
                    if verified and action == "reuse"
                    else "connected"
                    if action == "reuse"
                    else "planned"
                    if action != "review"
                    else "blocked"
                ),
                "sync_state": sync_state,
                "action": action,
                "detail": detail,
            }
        )
    return rows


def _department_seed(component: str, unit: str) -> str:
    return yaml.safe_dump(
        {
            "schema_version": "1.0",
            "package": {
                "role": "department",
                "rank": 20,
                "product": component,
                "unit": unit,
            },
            "dimensions": [],
        },
        sort_keys=False,
    )


def _seed_department(owner: str, name: str, component: str, unit: str, *, run: Run) -> bool:
    encoded = base64.b64encode(_department_seed(component, unit).encode("utf-8")).decode("ascii")
    result = run(
        (
            "gh", "api", "-X", "PUT",
            f"repos/{owner}/{name}/contents/copilot.layer.yml",
            "-f", f"message=Initialize {unit} {component} Copilot layer",
            "-f", f"content={encoded}",
        )
    )
    return result.returncode == 0


def _apply_visible_topology(
    manifest: dict[str, Any], rows: Sequence[dict[str, Any]], *, run: Run
) -> tuple[bool, str | None]:
    """Create/download/fast-forward only CLI-proven visible checkouts.

    ``row["action"]`` is read, never recomputed: it is the closed
    classification `_classify_repository_history` (task 204) already
    produced in `_topology_report_layers`, so only a row proven
    ``fast-forwardable`` ever reaches the ``repair`` branch below and every
    ``review`` row returns before any Git command touches its checkout
    (never-destroy).

    G-2 (task 205): a fast-forward merge exiting 0 is not proof it moved
    anything -- ``git merge --ff-only`` also exits 0 as a no-op when
    ``FETCH_HEAD`` is already an ancestor of ``HEAD``. So the repair branch
    asserts the postcondition ``git rev-parse HEAD`` equals the fetched
    target SHA before ever reporting success; a mismatch (or an
    unconfirmable revision) is reported failed, never synced. When the
    postcondition does hold, the row's ``detail`` is updated to say plainly
    whether a fast-forward actually happened or the checkout was already at
    the target -- "already at target" is its own honest outcome, never
    relabeled as "repaired".

    G-4 (task 207): every mutation this function actually completes for a
    row is also recorded onto that row as ``row["_ledger_entries"]`` -- a
    purely additive, internal-only key the caller drains into the run's
    ``completed_actions`` ledger once this returns, whether it returns
    ``True`` or stops partway with ``False``. `_ecosystem_result` never
    spreads unrecognized row keys into the emitted report (it copies only
    its own fixed ``optional_layer_fields`` tuple), so this key never
    reaches the JSON contract directly.
    """
    by_id = {row["id"]: row for row in rows}
    for layer in sorted(manifest["layers"], key=lambda item: item["rank"], reverse=True):
        row = by_id[layer["id"]]
        action = row["action"]
        if action in {"reuse"}:
            continue
        if action in {"review", "choose-location"}:
            return False, row["detail"]
        source = layer["source"]
        target = Path(source["path"]).expanduser()
        repo_full_name = f"{row['repository_owner']}/{row['repository_name']}"
        entries: list[dict[str, Any]] = []
        if action == "initialize":
            if not _seed_department(
                row["repository_owner"], row["repository_name"],
                layer["product"], layer.get("unit", ""), run=run,
            ):
                return False, f"GitHub did not confirm initialization of {row['repository_owner']}/{row['repository_name']}."
            entries.append(
                _ledger_entry(
                    kind="github-repository-content",
                    target=repo_full_name,
                    outcome="completed",
                    summary=f"Initialized the empty {repo_full_name} layer.",
                )
            )
            action = "download"
        if action in {"create", "download"}:
            if target.exists():
                return False, f"{target} appeared during setup, so Control Tower stopped without changing it."
            target.parent.mkdir(parents=True, exist_ok=True)
            clone = run(("git", "clone", "--origin", "origin", "--branch", source.get("ref", "main"), source["repo"], str(target)))
            if clone.returncode != 0:
                if target.exists() and not any(target.iterdir()):
                    target.rmdir()
                return False, f"Git could not download {row['repository_owner']}/{row['repository_name']} to {target}."
            cloned_head = _git_output(target, "rev-parse", "HEAD", run=run)
            entries.append(
                _ledger_entry(
                    kind="visible-repository",
                    target=repo_full_name,
                    outcome="completed",
                    summary=f"Placed a working copy of {repo_full_name} at {target}.",
                    local_path=str(target),
                    from_sha=None,
                    to_sha=cloned_head.stdout.strip() if cloned_head.returncode == 0 else None,
                    action=action,
                )
            )
        elif action == "repair":
            pre_merge_head = _git_output(target, "rev-parse", "HEAD", run=run)
            if pre_merge_head.returncode != 0:
                return False, f"{target}'s current revision could not be confirmed; nothing was changed."
            fetch = _git_output(target, "fetch", "origin", source.get("ref", "main"), run=run)
            if fetch.returncode != 0:
                return False, f"Git could not fetch {row['repository_owner']}/{row['repository_name']}."
            # `FETCH_HEAD^{commit}` peels an annotated tag object to the
            # commit it points at, mirroring `_classify_repository_history`
            # above -- `rev-parse` does not auto-peel, so an unpeeled
            # `target_sha` here would make the postcondition below fail even
            # after a genuinely successful fast-forward to an annotated tag.
            fetched_head = _git_output(target, "rev-parse", "FETCH_HEAD^{commit}", run=run)
            if fetched_head.returncode != 0:
                return False, f"Git could not resolve the fetched revision for {row['repository_owner']}/{row['repository_name']}."
            target_sha = fetched_head.stdout.strip()
            # `merge` (unlike `rev-parse`) treats an annotated tag object as
            # a commit-ish and peels it automatically, so merging the
            # unpeeled `FETCH_HEAD` ref here is safe and reaches the same
            # commit as `target_sha`.
            merge = _git_output(target, "merge", "--ff-only", "FETCH_HEAD", run=run)
            if merge.returncode != 0:
                return False, f"{target} could not be fast-forwarded safely; local work was preserved."
            post_merge_head = _git_output(target, "rev-parse", "HEAD", run=run)
            if post_merge_head.returncode != 0 or post_merge_head.stdout.strip() != target_sha:
                return False, (
                    f"{target} did not reach the expected revision after the fast-forward, "
                    "so Control Tower is reporting this failed rather than synced."
                )
            row["sync_state"] = "current"
            row["action"] = "reuse"
            already_current = pre_merge_head.stdout.strip() == target_sha
            row["detail"] = (
                f"{target} was already at the expected revision; no fast-forward was needed."
                if already_current
                else f"{target} was fast-forwarded to the expected revision."
            )
            entries.append(
                _ledger_entry(
                    kind="visible-repository",
                    target=repo_full_name,
                    outcome="completed",
                    summary=row["detail"],
                    local_path=str(target),
                    from_sha=pre_merge_head.stdout.strip(),
                    to_sha=target_sha,
                    action="already-current" if already_current else "repair",
                )
            )
        if entries:
            row["_ledger_entries"] = entries
    return True, None


def build_shared_repository_refresh_report(
    *,
    org: str = "auto",
    products: Sequence[str] = COMPONENTS,
    run: Run | None = None,
    repository_root: Path | str | None = None,
) -> dict[str, Any]:
    """Fast-forward only shared visible Copilot repositories.

    This is intentionally narrower than ecosystem onboarding.  It never
    creates or writes GitHub repository content, provisions SSH, changes the
    layer manifest, materializes consumers, or touches Personal repositories.
    Every shared checkout remains a download-only setup target even when the
    current GitHub account has author permission; that permission is reported
    solely as evidence for a separate explicit publishing workflow.
    """
    base_run = run or _run

    def setup_run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        """Run setup Git without repository hooks or filesystem monitors.

        A downloaded checkout is untrusted input during setup.  In particular,
        ``git merge --ff-only`` would ordinarily run a repository-provided
        ``post-merge`` hook.  Setup needs Git's normal credential and signing
        configuration, but it must not execute code discovered inside a shared
        repository while performing its download-only refresh.
        """
        if command and command[0] == "git":
            command = (
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                *command[1:],
            )
        return base_run(tuple(command))

    run = setup_run
    normalized = tuple(dict.fromkeys(value.strip().lower() for value in products))
    if not normalized or any(value not in COMPONENTS for value in normalized):
        raise ValueError("Supported shared components are required.")
    resolved_org = _discover_org(normalized, run=run) if org.casefold() == "auto" else org
    owner = _owner(run=run)
    handoff = _load_handoff(resolved_org, normalized, run=run)
    departments = _eligible_department_units(handoff, resolved_org, owner, run=run)
    visible_root = (
        Path(repository_root).expanduser()
        if repository_root is not None
        else _infer_repository_root(departments)
    )
    if visible_root is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "result": "blocked",
            "org": resolved_org,
            "mode": "download-only",
            "completed_actions": [],
            "layers": [],
            "summary": {"checked": 0, "updated": 0, "current": 0, "held": 1},
            "holds": [
                {
                    "code": "repository-root-unavailable",
                    "detail": "The visible Copilot repository folder could not be confirmed.",
                }
            ],
        }

    manifest = _layer_manifest(
        resolved_org,
        owner,
        normalized,
        handoff,
        run=run,
        department_units=departments,
        repository_root=visible_root,
    )
    rows = [
        row
        for row in _topology_report_layers(manifest, run=run)
        if row["role"] in {"foundation", "organization", "department"}
    ]
    layers_by_id = {layer["id"]: layer for layer in manifest["layers"]}
    completed_actions: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    current = 0

    for row in rows:
        action = row["action"]
        # Shared setup is pull-only. In particular, an empty Department repo
        # is never seeded here, even when GitHub reports WRITE or stronger.
        if action not in {"reuse", "repair", "download"}:
            holds.append(
                {
                    "code": "shared-repository-review-required",
                    "layer_id": row["id"],
                    "repository": f"{row['repository_owner']}/{row['repository_name']}",
                    "detail": row["detail"],
                }
            )
            continue
        if action == "reuse":
            current += 1
            continue
        one_layer_manifest = {
            "version": manifest["version"],
            "org": manifest["org"],
            "layers": [layers_by_id[row["id"]]],
        }
        ok, detail = _apply_visible_topology(one_layer_manifest, [row], run=run)
        entries = row.pop("_ledger_entries", None)
        if entries:
            completed_actions.extend(entries)
        if not ok:
            holds.append(
                {
                    "code": "shared-repository-refresh-failed",
                    "layer_id": row["id"],
                    "repository": f"{row['repository_owner']}/{row['repository_name']}",
                    "detail": detail or row["detail"],
                }
            )

    updated = sum(
        entry.get("action") in {"repair", "download"}
        and entry.get("outcome") == "completed"
        for entry in completed_actions
    )
    result = "partial" if holds and completed_actions else "blocked" if holds else "applied" if updated else "ready"
    return {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "org": resolved_org,
        "mode": "download-only",
        "completed_actions": completed_actions,
        "layers": rows,
        "authority": {
            "setup_access": "download-only",
            "author_capable": sum(bool(row["author_capable"]) for row in rows),
            "read_only": sum(not bool(row["author_capable"]) for row in rows),
            "unknown": sum(row["repository_permission"] == "unknown" for row in rows),
        },
        "summary": {
            "checked": len(rows),
            "updated": updated,
            "current": current,
            "held": len(holds),
        },
        "holds": holds,
    }


def _quarantine_legacy_personal_mirrors(
    manifest: dict[str, Any], *, mirrors_root: Path | str | None = None
) -> list[str]:
    """Move superseded hidden Personal checkouts out of the active mirror tree.

    A Personal repository's canonical checkout is the visible ``source.path``
    selected during onboarding. Older releases placed Claude/Codex Personal
    working copies directly below ``~/.copilot/mirrors`` and CLI/Knowledge
    copies below product subdirectories. Preserve those bytes in a recoverable
    sibling quarantine, but never leave them looking like active repositories.
    """
    configured = mirrors_root or resolve_key("paths.mirrors_root")
    active_root = (
        Path(str(configured)).expanduser()
        if configured
        else Path.home() / ".copilot" / "mirrors"
    )
    quarantine_root = active_root.parent / "legacy-mirrors"
    moved: list[str] = []
    for layer in manifest["layers"]:
        if layer.get("role") != "personal":
            continue
        layer_id = str(layer["id"])
        product = str(layer["product"])
        visible = Path(str(layer["source"]["path"])).expanduser().resolve()
        candidates = (active_root / layer_id, active_root / product / layer_id)
        for candidate in candidates:
            if not candidate.exists() or candidate.resolve() == visible:
                continue
            assert_write_is_isolated(candidate)
            quarantine_root.mkdir(parents=True, exist_ok=True)
            destination = quarantine_root / f"{product}-{layer_id}"
            suffix = 1
            while destination.exists():
                destination = quarantine_root / f"{product}-{layer_id}-{suffix}"
                suffix += 1
            candidate.rename(destination)
            moved.append(f"{candidate} -> {destination}")
    return moved


def _seed_cold_start_mirrors(
    manifest: dict[str, Any],
    *,
    mirrors_root: Path | str | None = None,
    latest_sha_fn: Callable[[str, str], str | None] | None = None,
    clone_fn: Callable[..., dict[str, Any]] | None = None,
) -> list[str]:
    """Best-effort seed the read-only mirror clone for a layer that has never
    published a ``refs/copilot/lock`` freshness pointer and has no mirror on
    disk yet (G-10, task 215 second blocker fix).

    A layer's FIRST appearance in ANY manifest this doctor ladder has ever
    checked can never have a pre-existing published freshness pointer or
    local mirror-clone fallback -- that is cold start, not corruption (see
    the doctor-gate fix in ``build_ecosystem_onboard_report``, below). This
    shrinks that window where cheap and honest: it reuses the SAME clone
    step ``cc update`` performs for its own hidden-mirror layers
    (``mirror.clone_or_update_mirror`` -- never duplicated here) so a layer
    whose content already lives at a VISIBLE checkout path (this apply's
    normal shape; ``_apply_visible_topology`` above never populates
    ``paths.mirrors_root`` for a layer with a local ``source.path``) also
    gets a real, git-verified local HEAD commit at the location doctor's own
    sync-checker fallback (``core/ecosystem/component_status.py``'s
    ``_mirror_clone_head_sha``) actually reads -- converting a "could not
    reach remote to verify sync" warning into a genuine ``pass``/``behind``
    verdict on this very first run.

    Deliberately narrow and never fatal to the caller: skips any layer that
    already publishes a lock-pointer ref (nothing to seed) or already has a
    local mirror (nothing new to adopt), and a clone that itself fails
    offline or errors is left exactly as honestly unverified as it was
    before -- this never fabricates a lock ref or sync state, and a failure
    here is never raised past this function (see its one call site's own
    ``try/except``, which exists only for a collaborator that misbehaves in
    a way this function itself does not).
    """
    configured = mirrors_root if mirrors_root is not None else resolve_key("paths.mirrors_root")
    if not configured:
        return []
    base = Path(str(configured)).expanduser()
    latest_sha = latest_sha_fn or mirror.latest_lock_sha
    clone = clone_fn or mirror.clone_or_update_mirror
    seeded: list[str] = []
    for layer in manifest.get("layers", []):
        source = layer.get("source") or {}
        repo = source.get("repo")
        layer_id = layer.get("id")
        if not repo or not layer_id:
            continue
        product = layer.get("product")
        product_root = (
            base / str(product) if product in mirror.EXTERNALLY_CONSUMED_PRODUCTS else base
        )
        if (product_root / str(layer_id) / ".git").is_dir():
            continue  # already has a local mirror -- nothing new to seed
        ref_pointer = source.get("lock_ref") or mirror.DEFAULT_LOCK_POINTER_REF
        try:
            if latest_sha(repo, ref_pointer) is not None:
                continue  # already publishes a freshness pointer -- no fallback needed
            transport = mirror.resolve_transport(repo, layer.get("auth", "anon"))
            result = clone(
                layer_id, transport, source.get("ref", "main"), mirror_root=product_root,
            )
        except Exception:
            continue
        if isinstance(result, dict) and result.get("ok"):
            seeded.append(str(layer_id))
    return seeded


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _resolve_foundation_ref(product: str, requested: str, *, run: Run) -> str:
    if _SEMVER.match(requested):
        return requested
    floor = (
        _SEMVER.match(requested.removeprefix("^"))
        if requested.startswith("^")
        else None
    )
    if floor is None:
        raise RuntimeError(f"Unsupported {product} foundation ref {requested!r}.")
    result = run(
        (
            "gh",
            "api",
            f"repos/Everyone-Needs-A-Copilot/{product}-copilot/tags",
            "--paginate",
        )
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"GitHub could not resolve the {product} foundation release."
        )
    try:
        tags = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"GitHub returned unreadable {product} release tags."
        ) from exc
    floor_version = tuple(int(value) for value in floor.groups())
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for item in tags if isinstance(tags, list) else []:
        name = item.get("name") if isinstance(item, dict) else None
        match = _SEMVER.match(name or "")
        if match:
            version = tuple(int(value) for value in match.groups())
            if version >= floor_version and version[0] == floor_version[0]:
                candidates.append((version, str(name)))
    if not candidates:
        raise RuntimeError(
            f"No published {product} foundation release satisfies {requested}."
        )
    return max(candidates)[1]


def _layer_manifest(
    org: str,
    owner: str,
    products: Sequence[str],
    handoff: dict[str, Any],
    *,
    run: Run,
    department_units: Sequence[str] = (),
    repository_root: Path | None = None,
) -> dict[str, Any]:
    refs = (handoff.get("foundation") or {}).get("refs") or {}
    layers: list[dict[str, Any]] = []
    for product in products:
        requested = refs.get(product) or LEGACY_FOUNDATION_REFS.get(product)
        if not isinstance(requested, str) or not requested:
            raise RuntimeError(
                f"The organization handoff is missing foundation.refs.{product}."
            )
        exact_ref = _resolve_foundation_ref(product, requested, run=run)
        personal_id = "cli-personal" if product == "cli" else f"{product}-personal"
        organization_id = "org-internal" if product == "cli" else f"{product}-organization"
        foundation_id = "foundation" if product == "cli" else f"{product}-foundation"
        private_foundation = product in {"knowledge", "cli"}
        foundation_repo = (
            f"git@github-work:Everyone-Needs-A-Copilot/{product}-copilot.git"
            if private_foundation
            else f"https://github.com/Everyone-Needs-A-Copilot/{product}-copilot.git"
        )
        layer_specs = [
            (
                personal_id,
                "personal",
                10,
                f"git@github-personal:{owner}/{product}-copilot-private.git",
                "main",
                "personal",
            ),
            *[
                (
                    f"{product}-department-{unit}",
                    "department",
                    20,
                    f"git@github-work:{org}/{product}-copilot-{unit}.git",
                    "main",
                    "work",
                )
                for unit in department_units
            ],
            (
                organization_id,
                "organization",
                30,
                f"git@github-work:{org}/{product}-copilot-internal.git",
                "main",
                "work",
            ),
            (
                foundation_id,
                "foundation",
                40,
                foundation_repo,
                exact_ref,
                "work" if private_foundation else "anon",
            ),
        ]
        for layer_id, role, rank, repo, ref, auth in layer_specs:
            source: dict[str, str] = {"repo": repo, "ref": ref}
            if repository_root is not None:
                if role == "personal":
                    repo_name = f"{product}-copilot-private"
                elif role == "department":
                    unit = next(
                        unit
                        for unit in department_units
                        if layer_id.endswith("-" + unit)
                    )
                    repo_name = f"{product}-copilot-{unit}"
                elif role == "organization":
                    repo_name = f"{product}-copilot-internal"
                else:
                    repo_name = f"{product}-copilot"
                source["path"] = str(repository_root / repo_name)
            if product == "claude" and role == "foundation":
                source["subpath"] = ".claude"
            layer = {
                    "id": layer_id,
                    "role": role,
                    "rank": rank,
                    "product": product,
                    "source": source,
                    "auth": auth,
                    "activation": "always",
                    "policy": {
                        "allowed_signers": list(FOUNDATION_ALLOWED_SIGNERS.get(product, ()))
                        if role == "foundation"
                        else []
                    },
                }
            if role == "department":
                layer["unit"] = next(
                    unit for unit in department_units if layer_id.endswith("-" + unit)
                )
            layers.append(layer)
    return {"version": 1, "org": org, "layers": layers}


def _atomic_yaml(path: Path, payload: dict[str, Any]) -> None:
    # Guard before mkdir/tempfile creation, not only before os.replace: a
    # pytest isolation escape must leave no directory or temporary artifact
    # behind at any of the real active/legacy manifest locations.
    assert_write_is_isolated(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(yaml.safe_dump(payload, sort_keys=False))
        temp = Path(handle.name)
    os.replace(temp, path)


def _existing_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a supported manifest without rewriting unrequested products.

    The first CLI inheritance release called the product discriminator
    ``component``. It is a deterministic predecessor of ``product`` and can
    therefore be compared through a normalized view. The raw view is retained
    for serialization so onboarding Claude or Codex cannot rewrite a CLI,
    Knowledge, or future product layer as an unrelated side effect.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(
            "The existing layer manifest could not be read safely."
        ) from exc
    if (
        not isinstance(raw, dict)
        or raw.get("version") != 1
        or not isinstance(raw.get("layers"), list)
    ):
        raise ManifestError(
            "The existing layer manifest is not a supported version-1 manifest."
        )

    normalized: list[dict[str, Any]] = []
    for raw_layer in raw["layers"]:
        if not isinstance(raw_layer, dict):
            raise ManifestError(
                "The existing layer manifest contains an unfamiliar layer."
            )
        layer = normalize_layer_product(raw_layer)
        layer.setdefault("activation", "always")
        if not _safe_repository_reference((layer.get("source") or {}).get("repo")):
            raise ManifestError(
                "The existing layer manifest contains an unsafe repository reference."
            )
        normalized.append(layer)
    validate_layers(normalized)
    normalized_result = dict(raw)
    normalized_result["layers"] = normalized
    return raw, normalized_result


def _managed_product_is_compatible(
    existing: list[dict[str, Any]], desired: list[dict[str, Any]]
) -> bool:
    """Return true only for a previously generated stack we can repair."""
    if not existing:
        return False
    def canonical_role(value: Any) -> Any:
        return {
            "org": "organization",
            "organization": "organization",
            "dept": "department",
            "department": "department",
        }.get(value, value)
    desired_by_key = {
        (layer.get("product"), canonical_role(layer.get("role"))): layer
        for layer in desired
    }
    allowed_keys = {
        "id",
        "role",
        "rank",
        "product",
        "unit",
        "source",
        "auth",
        "activation",
        "policy",
    }
    auth_equivalents = (
        {"personal", "ssh-personal"},
        {"work", "ssh-work"},
        {"anon"},
    )
    for layer in existing:
        key = (layer.get("product"), canonical_role(layer.get("role")))
        expected = desired_by_key.get(key)
        if expected is None:
            return False
        recognized_ids = {expected["id"]}
        if layer.get("product") == "cli":
            recognized_ids.update(
                {
                    "personal": {"cli-personal"},
                    "organization": {"cli-organization", "org-internal"},
                    "foundation": {"cli-foundation", "foundation"},
                }.get(canonical_role(layer.get("role")), set())
            )
        if layer.get("id") not in recognized_ids:
            return False
        if set(layer) - allowed_keys:
            return False
        actual_role = canonical_role(layer.get("role"))
        expected_role = canonical_role(expected.get("role"))
        if actual_role != expected_role or any(
            layer.get(key) != expected.get(key)
            for key in ("rank", "product", "unit")
        ):
            return False
        actual_source = layer.get("source") or {}
        expected_source = expected.get("source") or {}
        if _repository_identity(actual_source.get("repo")) != _repository_identity(
            expected_source.get("repo")
        ):
            return False
        if actual_source.get("subpath") != expected_source.get("subpath"):
            return False
        if expected["role"] != "foundation" and actual_source.get(
            "ref"
        ) != expected_source.get("ref"):
            return False
        actual_auth, expected_auth = layer.get("auth"), expected.get("auth")
        foundation_transport_upgrade = (
            expected_role == "foundation"
            and {actual_auth, expected_auth} <= {"anon", "work", "ssh-work"}
        )
        if not foundation_transport_upgrade and not any(
            {actual_auth, expected_auth} <= group for group in auth_equivalents
        ):
            return False
        if layer.get("activation", "always") != "always":
            return False
    return True


def _manifest_adoption_plan(
    desired: dict[str, Any],
    destination: Path,
    *,
    configured_path: Path | str | None = None,
    legacy_paths: Sequence[Path | str] = (),
    allowed_root: Path | str | None = None,
) -> ManifestAdoption:
    """Inventory and merge a recognized existing manifest without data loss."""
    destination = destination.expanduser()
    candidates: list[Path] = [destination]
    if configured_path:
        candidates.append(Path(configured_path).expanduser())
    candidates.extend(Path(path).expanduser() for path in legacy_paths)

    source = next((path for path in dict.fromkeys(candidates) if path.is_file()), None)
    if source is None:
        return ManifestAdoption(
            "missing",
            "create",
            "Nothing is connected yet. Setup will connect all of it for you.",
            None,
            destination,
            desired,
        )
    if source.is_symlink() or destination.is_symlink():
        return ManifestAdoption(
            "unfamiliar",
            "review",
            "This is set up through a link I don't manage, so I'll leave it untouched until it's looked at.",
            source,
            destination,
            None,
        )
    if allowed_root is not None:
        try:
            root = Path(allowed_root).expanduser().resolve()
            source.resolve().relative_to(root)
            destination.resolve().relative_to(root)
        except (OSError, ValueError):
            return ManifestAdoption(
                "unfamiliar",
                "review",
                "Something is set up somewhere I don't manage, so I'll leave it untouched.",
                source,
                destination,
                None,
            )
    try:
        existing_raw, existing = _existing_manifest(source)
    except ManifestError:
        return ManifestAdoption(
            "unfamiliar",
            "review",
            "I don't recognize an existing setting here, so I'll leave it untouched until it's looked at.",
            source,
            destination,
            None,
        )

    desired_layers = list(desired["layers"])
    desired_products = {layer["product"] for layer in desired_layers}
    retained = [
        raw_layer
        for raw_layer, normalized_layer in zip(
            existing_raw["layers"], existing["layers"], strict=True
        )
        if normalized_layer["product"] not in desired_products
    ]
    existing_managed = [
        layer for layer in existing["layers"] if layer["product"] in desired_products
    ]
    if existing_managed and not _managed_product_is_compatible(
        existing_managed, desired_layers
    ):
        return ManifestAdoption(
            "conflict",
            "review",
            "Your existing Claude or Codex setup isn't one I recognize, so I won't replace any of it.",
            source,
            destination,
            None,
        )

    existing_org = existing_raw.get("org")
    desired_org = desired.get("org")
    if existing_org not in (None, desired_org):
        return ManifestAdoption(
            "conflict",
            "review",
            "This manifest belongs to a different organization, so I won't replace it.",
            source,
            destination,
            None,
        )
    merged = dict(existing_raw)
    merged["version"] = 1
    if desired_org:
        merged["org"] = desired_org
    merged["layers"] = [*retained, *desired_layers]
    try:
        validate_layers(
            [
                {
                    **normalize_layer_product(layer),
                    "activation": layer.get("activation", "always"),
                }
                for layer in merged["layers"]
            ]
        )
    except ManifestError:
        return ManifestAdoption(
            "conflict",
            "review",
            "The existing and planned layers cannot be combined safely. Nothing will be replaced.",
            source,
            destination,
            None,
        )

    if source == destination and existing_raw == merged:
        return ManifestAdoption(
            "ready",
            "reuse",
            "Everything is already described correctly, so I'll keep it as it is.",
            source,
            destination,
            merged,
        )
    if source != destination:
        return ManifestAdoption(
            "legacy",
            "migrate",
            "I recognize an earlier setup. I'll bring it forward and add what's missing, keeping a copy first.",
            source,
            destination,
            merged,
        )
    return ManifestAdoption(
        "partial",
        "repair",
        "What's already set up will be kept, and I'll add the parts that are missing.",
        source,
        destination,
        merged,
    )


def _backup_path(path: Path) -> Path:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    root = path.parent / ".copilot-control-tower-backups" / digest
    return root / path.name


def _apply_manifest_adoption(plan: ManifestAdoption) -> Path | None:
    """Apply a reviewed manifest plan with a content-addressed rollback copy."""
    if plan.action == "review" or plan.payload is None:
        raise RuntimeError(
            "The existing layer manifest needs review before setup can continue."
        )
    if plan.action == "reuse":
        return None

    backup: Path | None = None
    if plan.source is not None and plan.source.is_file():
        backup = _backup_path(plan.source)
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.source, backup)
    _atomic_yaml(plan.destination, plan.payload)
    if (
        plan.action == "migrate"
        and plan.source is not None
        and plan.source != plan.destination
    ):
        # Remove only the byte-for-byte source that was just backed up. If a
        # concurrent actor changed it, preserve it and leave duplicate
        # recognized manifests rather than risking authored work.
        if backup is not None and plan.source.read_bytes() == backup.read_bytes():
            plan.source.unlink()
    return backup


def _atomic_bytes(path: Path, content: bytes) -> None:
    """Replace one controlled file while preserving its exact prior bytes."""
    assert_write_is_isolated(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp = Path(handle.name)
    os.replace(temp, path)


def _rollback_manifest_adoption(plan: ManifestAdoption, backup: Path | None) -> bool:
    """Restore the exact pre-transaction manifest when a later gate fails.

    The rollback refuses to overwrite concurrent edits: the destination must
    still equal the payload this transaction wrote, and a migrated source must
    still be absent (or already equal its backup).
    """
    if plan.action == "reuse":
        return True
    expected = yaml.safe_dump(plan.payload, sort_keys=False).encode()
    try:
        if not plan.destination.is_file() or plan.destination.read_bytes() != expected:
            return False
        if plan.source is None:
            plan.destination.unlink()
            return True
        if backup is None or not backup.is_file():
            return False
        prior = backup.read_bytes()
        if plan.source == plan.destination:
            _atomic_bytes(plan.destination, prior)
            return True
        if plan.source.exists() and plan.source.read_bytes() != prior:
            return False
        if not plan.source.exists():
            _atomic_bytes(plan.source, prior)
        plan.destination.unlink()
        return True
    except OSError:
        return False


def _copilot_layers_payload(manifest_path: Path) -> tuple[dict[str, Any] | None, str]:
    """Ask the installed CLI to resolve one candidate manifest."""
    executable = resolve_executable("copilot")
    if executable is None:
        return None, "The installed `copilot` command is unavailable."
    environment = os.environ.copy()
    environment["COPILOT_LAYERS_FILE"] = str(manifest_path)
    try:
        result = subprocess.run(
            (str(executable), "--json", "layers"),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"The installed `copilot` reader could not be checked: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        return None, f"The installed `copilot` reader rejected the manifest: {detail}"
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "The installed `copilot` reader returned unreadable output."
    if not isinstance(payload, dict):
        return None, "The installed `copilot` reader returned an unfamiliar report."
    return payload, ""


def _probe_cli_candidate(candidate: Path, baseline: Path | None) -> dict[str, str]:
    """Reject a candidate that removes CLI layers or visible capabilities."""
    candidate_layers = load_layers(candidate)
    expected_chain = [
        {
            "id": layer["id"],
            "role": layer["role"],
            "rank": layer["rank"],
            "repo": layer["source"]["repo"],
            "ref": layer["source"].get("ref"),
            "auth": layer["auth"],
            "unit": layer.get("unit"),
        }
        for layer in candidate_layers
        if layer["product"] == "cli"
    ]
    if not expected_chain:
        return {"result": "ready"}

    candidate_payload, detail = _copilot_layers_payload(candidate)
    if candidate_payload is None:
        return {"result": "blocked", "detail": detail}
    resolved_chain = [
        {
            key: layer.get(key)
            for key in ("id", "role", "rank", "repo", "ref", "auth", "unit")
        }
        for layer in candidate_payload.get("chain", [])
        if isinstance(layer, dict)
    ]
    if resolved_chain != expected_chain:
        return {
            "result": "blocked",
            "detail": (
                "The installed `copilot` reader would change or lose CLI layers "
                f"(expected {[item['id'] for item in expected_chain]}, "
                f"resolved {[item['id'] for item in resolved_chain]})."
            ),
        }

    if baseline is not None and baseline.is_file():
        baseline_payload, _ = _copilot_layers_payload(baseline)
        if baseline_payload is not None:
            before = {
                service.get("name"): (service.get("tier"), service.get("mode"))
                for service in baseline_payload.get("services", [])
                if isinstance(service, dict) and service.get("name")
            }
            after = {
                service.get("name"): (service.get("tier"), service.get("mode"))
                for service in candidate_payload.get("services", [])
                if isinstance(service, dict) and service.get("name")
            }
            changed = sorted(
                name
                for name, provenance in before.items()
                if after.get(name) != provenance
            )
            if changed:
                return {
                    "result": "blocked",
                    "detail": (
                        "The candidate would remove or downgrade installed CLI "
                        "capabilities: " + ", ".join(changed)
                    ),
                }
    return {"result": "ready"}


def _validate_manifest_candidate(
    plan: ManifestAdoption,
    probe: Callable[[Path, Path | None], dict[str, str]],
) -> dict[str, str]:
    """Validate staged bytes with cc and every relevant installed consumer."""
    if plan.payload is None:
        return {
            "result": "blocked",
            "detail": "No safe layer-manifest candidate was available.",
        }
    if plan.action == "reuse":
        candidate = plan.destination
        if not candidate.is_file() and plan.source is not None:
            candidate = plan.source
        return probe(candidate, plan.source)

    with tempfile.TemporaryDirectory(prefix="cc-manifest-candidate-") as temp_root:
        candidate = Path(temp_root) / "copilot.layers.yml"
        candidate.write_text(
            yaml.safe_dump(plan.payload, sort_keys=False), encoding="utf-8"
        )
        try:
            validate_layers(load_layers(candidate))
        except ManifestError as exc:
            return {
                "result": "blocked",
                "detail": f"The staged layer manifest is invalid: {exc}",
            }
        return probe(candidate, plan.source)


def _sync_cli_manifest(manifest_path: Path) -> dict[str, str]:
    """Sync CLI Copilot's product-owned mirrors against one staged manifest."""
    executable = resolve_executable("copilot")
    if executable is None:
        return {
            "result": "blocked",
            "detail": "The installed `copilot` command is unavailable.",
        }
    environment = os.environ.copy()
    environment["COPILOT_LAYERS_FILE"] = str(manifest_path)
    configured_root = resolve_key("paths.mirrors_root")
    if configured_root:
        # CLI Copilot's compatibility variable names the directory *above*
        # its `mirrors/cli/<id>` tree; cc stores the shared mirrors directory.
        environment["COPILOT_MIRRORS_ROOT"] = str(
            Path(str(configured_root)).expanduser().parent
        )
    try:
        result = subprocess.run(
            (str(executable), "--json", "update"),
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"result": "blocked", "detail": f"CLI sync could not run: {exc}"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    if result.returncode != 0 or payload.get("overall") != "ok":
        detail = (
            payload.get("detail")
            or result.stderr.strip()
            or result.stdout.strip()
            or "CLI Copilot did not confirm its layer mirrors."
        )
        return {"result": "blocked", "detail": str(detail)}
    return {"result": "ready"}


def _knowledge_mirror_paths(manifest: dict[str, Any]) -> list[str]:
    base = Path(str(resolve_key("paths.mirrors_root"))).expanduser()
    return [
        str(base / "knowledge" / layer["id"])
        for layer in sorted(manifest["layers"], key=lambda item: item["rank"])
        if layer.get("product") == "knowledge"
    ]


def _set_dotted(payload: dict[str, Any], key: str, value: Any) -> None:
    current = payload
    parts = key.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _commit_machine_pointers(
    manifest_path: Path,
    knowledge_paths: Sequence[str],
    repository_root: Path | None = None,
) -> Path:
    """Commit topology and Knowledge consumption pointers in one atomic write."""
    path = machine_config_path()
    payload = load_machine_config()
    if not payload:
        payload = {"$schema": "cc-config-v1", "version": 1}
    _set_dotted(payload, "layers.manifest", str(manifest_path))
    _set_dotted(payload, "paths.knowledge_repo", list(knowledge_paths))
    if repository_root is not None:
        _set_dotted(payload, "paths.repositories_root", str(repository_root))
    content = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    _atomic_bytes(path, content)
    return path

def _provision_store(store: dict[str, Any], *, apply: bool, run: Run) -> dict[str, Any]:
    """Confirm (or, in apply mode only, bootstrap) this Mac's access to the
    organization's shared Infisical store.

    HISTORY (WP-388/389, task 221): this used to call
    `copilot infisical identity provision`, a subcommand that has never
    existed in real `copilot infisical` builds (`identity`'s only
    subcommands are `list`/`create` -- confirmed live,
    `copilot infisical identity --help`). Empty stdout from that
    nonexistent command always failed to parse as JSON, so this stage
    could only ever report `deferred`, regardless of how correctly the
    Admin handoff's `store:` block was configured. That defect is fixed
    here by calling the REAL surface instead.

    DESIGN: `copilot infisical --json identity list` both (a) proves this
    Mac's already-configured Infisical credentials are valid and reachable
    (the call itself requires successful org authentication to return
    anything at all -- there is no anonymous/unauthenticated path) and (b)
    happens to enumerate every machine identity in the org, including
    -- necessarily -- whichever identity THIS Mac's own credentials
    authenticated as. So a successful, non-empty `list` is read as `ready`
    outright; a successful-but-genuinely-empty `list` (the org has never
    had ANY machine identity provisioned -- a one-time bootstrap gap, not
    a per-Mac state, and one the calling credentials' own successful
    authentication makes practically unreachable in production) falls
    through to a `create` call, but ONLY when `apply` is true --
    `identity create` has no dry-run/undo (`infisical identity` exposes no
    `delete`), so a plan-mode call must never risk creating a permanent
    org-wide identity; plan mode instead reports `deferred` with an
    honest "will create one on apply" detail, mirroring
    `ssh_identity.py`'s own plan/apply split for an equivalent
    doesn't-exist-yet-but-creatable device credential. `create`'s own
    response body is never inspected beyond parse-and-exit-code (it may
    carry fresh universal-auth credentials -- this stage never reads,
    stores, or forwards ANY field from it, only whether the call
    succeeded)."""
    if store.get("status") != "connected":
        return {"result": "deferred"}
    if store.get("type") != "infisical":
        return {
            "result": "blocked",
            "detail": "Automated device identity provisioning currently supports Infisical.",
        }
    required = ("workspace_id", "environment", "secret_path")
    if not all(isinstance(store.get(key), str) and store.get(key) for key in required):
        return {
            "result": "blocked",
            "detail": "The Admin handoff is missing workspace_id, environment, or secret_path.",
        }
    # The onboarding contract deliberately exposes only a non-secret summary
    # string; its schema does not accept arbitrary nested policy.
    scope = f"{store['environment']}:{store['secret_path']}:read"
    unreachable = {
        "result": "deferred",
        "type": "infisical",
        "detail": (
            "The shared credential store could not be connected on this Mac. "
            "Setup kept this Mac's existing credentials and will continue "
            "without shared integrations."
        ),
    }

    list_result = run(("copilot", "infisical", "--json", "identity", "list"))
    try:
        identities = json.loads(list_result.stdout)
    except json.JSONDecodeError:
        return unreachable
    if list_result.returncode != 0 or not isinstance(identities, list):
        return unreachable
    if identities:
        return {"result": "ready", "type": "infisical", "scope": scope}
    if not apply:
        return {
            "result": "deferred",
            "type": "infisical",
            "detail": (
                "No machine identity exists yet for the organization's shared "
                "credential store. Setup will create one the next time changes "
                "are applied."
            ),
        }
    identity_name = f"copilot-{socket.gethostname()}"
    create_result = run(
        ("copilot", "infisical", "--json", "identity", "create", identity_name)
    )
    if create_result.returncode != 0:
        return unreachable
    try:
        json.loads(create_result.stdout)
    except json.JSONDecodeError:
        return unreachable
    return {"result": "ready", "type": "infisical", "scope": scope}


def _codex_marketplace_failure(result: subprocess.CompletedProcess[str]) -> str:
    if result.returncode == 127 and result.stderr.startswith("codex is not installed"):
        return "Codex is not installed in a supported location on this Mac."
    if result.returncode == 127 and "runtime required by codex" in result.stderr:
        return (
            "Codex is installed, but its required command-line runtime "
            "could not be started outside the terminal."
        )
    return "Codex rejected the verified local marketplace."


def _install_codex_plugin(*, apply: bool, run: Run) -> dict[str, Any]:
    root = Path(str(resolve_key("paths.codex_materialize_root"))).expanduser()
    plugin = root / "plugins" / "codex-copilot"
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    if not apply:
        if (
            not plugin.joinpath(".codex-plugin", "plugin.json").is_file()
            or not marketplace.is_file()
        ):
            return {"result": "changes-required"}
        listed_marketplaces = run(("codex", "plugin", "marketplace", "list", "--json"))
        if listed_marketplaces.returncode != 0:
            return {
                "result": "blocked",
                "detail": _codex_marketplace_failure(listed_marketplaces),
            }
        try:
            marketplace_payload = json.loads(listed_marketplaces.stdout)
            registered = any(
                row.get("name") == "enac-materialized"
                and isinstance(row.get("root"), str)
                and Path(row.get("root", "")).expanduser().resolve() == root.resolve()
                for row in marketplace_payload["marketplaces"]
            )
        except (json.JSONDecodeError, KeyError, OSError, TypeError):
            return {
                "result": "blocked",
                "detail": "Codex returned an unreadable marketplace inventory.",
            }
        if not registered:
            return {"result": "changes-required"}
        listed_plugins = run(("codex", "plugin", "list", "--json"))
        if listed_plugins.returncode != 0:
            return {
                "result": "blocked",
                "detail": "Codex could not inspect installed plugins.",
            }
        try:
            plugin_payload = json.loads(listed_plugins.stdout)
            ready = any(
                row.get("pluginId") == "codex-copilot@enac-materialized"
                and row.get("installed") is True
                and row.get("enabled") is True
                for row in plugin_payload["installed"]
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return {
                "result": "blocked",
                "detail": "Codex returned an unreadable plugin inventory.",
            }
        return {"result": "ready" if ready else "changes-required"}
    if not plugin.joinpath(".codex-plugin", "plugin.json").is_file():
        return {
            "result": "blocked",
            "detail": "The verified Codex Copilot plugin was not materialized.",
        }
    payload = {
        "name": "enac-materialized",
        "interface": {"displayName": "Copilot Control Tower"},
        "plugins": [
            {
                "name": "codex-copilot",
                "source": {"source": "local", "path": "./plugins/codex-copilot"},
                "policy": {
                    "installation": "INSTALLED_BY_DEFAULT",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=marketplace.parent, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, marketplace)
    added = run(("codex", "plugin", "marketplace", "add", str(root), "--json"))
    if added.returncode != 0:
        return {
            "result": "blocked",
            "detail": _codex_marketplace_failure(added),
        }
    installed = run(
        ("codex", "plugin", "add", "codex-copilot@enac-materialized", "--json")
    )
    if installed.returncode != 0:
        return {
            "result": "blocked",
            "detail": "Codex rejected the Codex Copilot plugin installation.",
        }
    return {"result": "ready"}


def _ledger_entry(
    kind: str,
    target: str,
    outcome: str,
    summary: str,
    **fields: Any,
) -> dict[str, Any]:
    """One `completed_actions` ledger row (G-4, task 207): a mutation this
    run actually performed, or attempted, against the account/device/local
    disk -- recorded as it happens, never reconstructed after the fact from
    a final "did the whole run succeed" boolean.

    ``kind`` is a machine-readable mutation family (``github-repository``,
    ``github-repository-content``, ``ssh-keypair``, ``ssh-key-registration``,
    ``layer-manifest``, ``visible-repository``, ``materialization``, ...);
    ``target`` names exactly what was touched (an ``owner/name`` GitHub
    repository, a device SSH key title, a manifest path, a local checkout
    path); ``outcome`` is one of exactly ``completed``/``failed``/
    ``rolled-back`` -- the only three states a recorded mutation can settle
    into (mirroring ``HistoryClassification``'s discipline of never inventing
    a fourth state). Every other keyword becomes a kind-specific field (for
    example ``url``, ``from_sha``, ``to_sha``, ``backup_path``,
    ``local_path``, ``action``). Task 208 formalizes the closed shape of this
    contract; this stays deliberately permissive so it never has to be
    revisited to add a field.
    """
    entry: dict[str, Any] = {
        "kind": kind,
        "target": target,
        "outcome": outcome,
        "summary": summary,
    }
    entry.update(fields)
    return entry


def _personal_ledger_entries(personal: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate one `apply=True` personal-packages report into ledger rows.

    `build_personal_onboard_report` already closes over exactly what
    happened to each repository (`state == "created"`) and each package
    marker (`package_state in {"seeded", "adopted"}` on success,
    `package_action == "blocked"` on failure) -- this only relabels that
    closed vocabulary onto the ledger's shape, it never re-derives it.
    """
    entries: list[dict[str, Any]] = []
    for row in personal.get("repositories", []):
        owner = row.get("owner")
        name = row.get("name")
        if not owner or not name:
            continue
        full_name = f"{owner}/{name}"
        url = f"https://github.com/{full_name}"
        if row.get("state") == "created":
            entries.append(
                _ledger_entry(
                    kind="github-repository",
                    target=full_name,
                    outcome="completed",
                    summary=f"Created the private GitHub repository {full_name}.",
                    url=url,
                )
            )
        package_state = row.get("package_state")
        if package_state in {"seeded", "adopted"}:
            entries.append(
                _ledger_entry(
                    kind="github-repository-content",
                    target=full_name,
                    outcome="completed",
                    summary=(
                        f"Set up the Copilot package marker in {full_name}."
                        if package_state == "seeded"
                        else f"Marked your existing content in {full_name} as part of your copilots."
                    ),
                    url=url,
                )
            )
        elif row.get("package_action") == "blocked" and row.get("state") in {
            "created",
            "existing-private",
        }:
            entries.append(
                _ledger_entry(
                    kind="github-repository-content",
                    target=full_name,
                    outcome="failed",
                    summary=row.get("package_detail")
                    or f"Could not confirm the change to {full_name}.",
                    url=url,
                )
            )
    return entries


def _ssh_ledger_entries(ssh: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate one `apply=True` device-SSH report into ledger rows.

    Only fires on the additive fields `ensure_machine_ssh_identity` sets
    when it actually generated a keypair or actually registered one with
    GitHub this call (`key_created`/`key_registered`); a stub `ssh_fn` test
    double that omits them contributes nothing here, exactly as it should
    since it performed no real mutation.
    """
    entries: list[dict[str, Any]] = []
    title = ssh.get("key_title")
    target = title or "this Mac's GitHub SSH key"
    if ssh.get("key_created"):
        entries.append(
            _ledger_entry(
                kind="ssh-keypair",
                target=target,
                outcome="completed",
                summary="Generated a new, encrypted SSH keypair for this Mac.",
            )
        )
    if ssh.get("key_registered"):
        entries.append(
            _ledger_entry(
                kind="ssh-key-registration",
                target=target,
                outcome="completed",
                summary=(
                    f'Registered this Mac\'s public SSH key with GitHub as "{title}".'
                    if title
                    else "Registered this Mac's public SSH key with GitHub."
                ),
            )
        )
    return entries


def _resume_hint(completed_actions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """G-4's honesty guarantee for a stopped or failed run (task 207): what,
    if anything, already exists, and that re-running reuses it rather than
    recreating it. Never-destroy means a created GitHub repository or a
    registered device key is never rolled back (see `build_ecosystem_onboard_report`'s
    `blocked_after_write`), so the only honest promise on retry is adoption,
    never recreation.
    """
    completed = [
        entry for entry in completed_actions if entry.get("outcome") == "completed"
    ]
    if completed:
        kinds = sorted({entry["kind"] for entry in completed})
        return {
            "safe_to_rerun": True,
            "detail": (
                "Running setup again is safe: it will find and reuse what's "
                "already been created or registered rather than recreating "
                "it, and continue from where this stopped."
            ),
            "already_completed_kinds": kinds,
        }
    if completed_actions:
        # Everything this ledger recorded was fully undone (the only
        # `outcome` that can follow `completed` besides staying `completed`
        # is `rolled-back`) -- honest to say nothing survives, but distinct
        # from a run that never wrote anything in the first place.
        return {
            "safe_to_rerun": True,
            "detail": (
                "Everything this attempt wrote was fully undone before it "
                "stopped, so running setup again starts from the beginning."
            ),
        }
    return {
        "safe_to_rerun": True,
        "detail": (
            "Nothing on this Mac or on GitHub was changed before this "
            "stopped, so running setup again starts from the beginning."
        ),
    }


def _materialize_summary(update: dict[str, Any]) -> dict[str, Any]:
    """The honest, per-item materialize outcome (G-9, task 215 blocker fix).

    Reuses the SAME `held_for_approval`/`blocked` item shapes `update.py`'s
    own `--json` contract already emits (product/dimension/from/to/reason
    for a hold; product/dimension/layer/item/reason for a block) -- never a
    new vocabulary -- so a `held`/`blocked` outcome is surfaced plainly on
    the onboarding report without this transaction's manifest write or
    overall `result` ever being made hostage to it (see the apply loop's
    materialize step, above).
    """
    held_items = update.get("held_for_approval", [])
    blocked_items = update.get("blocked", [])
    return {
        "result": update.get("result", "blocked"),
        "completed": len(update.get("changed", [])),
        "held": len(held_items),
        "blocked": len(blocked_items),
        "held_items": held_items,
        "blocked_items": blocked_items,
    }


def _ecosystem_result(
    org: str,
    products: Sequence[str],
    apply: bool,
    result: str,
    stages: list[dict[str, Any]],
    layers: Sequence[dict[str, Any]] | None = None,
    inventory: Sequence[dict[str, Any]] | None = None,
    components: Sequence[str] | None = None,
    completed_actions: Sequence[dict[str, Any]] | None = None,
    materialize: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": SCHEMA_VERSION,
        "scope": "ecosystem",
        "mode": "apply" if apply else "plan",
        "result": result,
        "org": org,
        "products": list(products),
        "components": list(components or products),
        "stages": stages,
    }
    report["completed_actions"] = list(completed_actions or ())
    # G-4 (task 207): a result may only claim nothing changed when the
    # ledger above is actually empty -- this is enforced by never omitting
    # it, not by trusting `result` alone. `blocked` is the only result that
    # can follow a mutation, so it is the only one that carries a resume
    # hint; `changes-required` never mutated anything (it is always the
    # `apply=False` plan path).
    if result == "blocked":
        report["resume"] = _resume_hint(report["completed_actions"])
    # G-5 (task 208): `layers` is only ever omitted by a caller when the
    # topology report genuinely has not been computed yet on this exit path
    # -- the one early block that returns before `_layer_manifest`/
    # `_topology_report_layers` have ever run. That is this schema's one
    # legal typed absence (`layers_state: "not-computed"`, `layers: []`),
    # never a skeletal look-alike. Every other caller passes the
    # already-closed `topology_layers` rows from `_topology_report_layers`,
    # so `layers_state: "reported"` always means one fully-populated
    # topology row per layer.
    report["layers_state"] = "reported" if layers is not None else "not-computed"
    report["layers"] = []
    optional_layer_fields = (
        "unit",
        "repository_owner",
        "repository_name",
        "repository_visibility",
        "repository_permission",
        "author_capable",
        "setup_access",
        "remote_state",
        "local_path",
        "local_state",
        "connection_state",
        "sync_state",
        "action",
        "detail",
    )
    for layer in (layers or ()):
        row = {
            "id": layer["id"],
            "product": layer["product"],
            "role": layer["role"],
            "rank": layer["rank"],
        }
        row.update({key: layer.get(key) for key in optional_layer_fields if key in layer})
        report["layers"].append(row)
    report["inventory"] = list(inventory or ())
    report["inventory_summary"] = {
        "reused": sum(item.get("action") == "reuse" for item in report["inventory"]),
        "changes": sum(
            item.get("action") in {"create", "migrate", "repair"}
            for item in report["inventory"]
        ),
        "review": sum(item.get("action") == "review" for item in report["inventory"]),
    }
    # G-9 (task 215 blocker fix): purely additive/optional -- only present
    # once a real apply has actually run the materialize step; never `null`,
    # never a key that appears with placeholder/empty content on a path
    # that never reached materialize (plan mode, or any earlier block).
    # Carries the SAME per-item `held_for_approval`/`blocked` shapes
    # `update.py`'s own `--json` contract already emits, so a `held`/
    # `blocked` outcome here is reported honestly without ever making the
    # manifest write (already committed above) or this transaction's
    # overall `result` hostage to it.
    if materialize is not None:
        report["materialize"] = materialize
    return report


def _personal_inventory(personal: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in personal.get("repositories", []):
        component = row.get("component", "unknown")
        package_state = row.get("package_state")
        # `adoptable` is a pure offer (B1): it needs a `create`-shaped action
        # so a plan whose only open item is an offer to include existing
        # content is honestly "changes-required", never silently "ready" and
        # never conflated with a genuine `held`/unfamiliar `review`.
        action = (
            "create"
            if row.get("state") == "missing" or package_state in {"empty", "adoptable"}
            else "reuse"
            if package_state in {"ready", "seeded", "adopted"}
            else "review"
        )
        items.append(
            {
                "id": f"personal-{component}",
                "scope": "personal",
                "title": f"Your {_component_label(component)} Copilot space",
                "state": package_state or row.get("state", "unknown"),
                "action": action,
                "detail": row.get("package_detail") or row.get("detail") or "",
                "source_path": None,
                "destination_path": None,
                # An adoptable offer is reversible (nothing has been written
                # yet, and declining costs nothing); every other state here
                # keeps the prior unconditional False.
                "reversible": package_state == "adoptable",
                "decline_detail": row.get("decline_detail") or "",
            }
        )
    return items


# The `ecosystemStage` schema entry declares `additionalProperties: false`,
# so only these fields from an `ensure_machine_ssh_identity` report may be
# spread into the `device-ssh` stage; richer fields (`decline_detail`,
# `adopted_alias`, `missing_alias`) are consumed by `_ssh_inventory` instead.
_SSH_STAGE_FIELDS = ("result", "key", "registration", "config", "detail")


def _ssh_stage_fields(ssh: dict[str, Any]) -> dict[str, Any]:
    return {key: ssh[key] for key in _SSH_STAGE_FIELDS if key in ssh}


def _ssh_inventory(ssh: dict[str, Any]) -> list[dict[str, Any]]:
    """An adoptable SSH alias is a pure offer (B1), the same shape as an
    adoptable personal package: a `create`-shaped action, reversible because
    nothing has been written yet, with a cost-of-declining detail.
    """
    if ssh.get("config") != "adoptable":
        return []
    return [
        {
            "id": "device-ssh",
            "scope": "machine",
            "title": "Your Mac's connection to GitHub",
            "state": "adoptable",
            "action": "create",
            "detail": ssh.get("detail") or "",
            "source_path": None,
            "destination_path": None,
            "reversible": True,
            "decline_detail": ssh.get("decline_detail") or "",
        }
    ]


def build_ecosystem_onboard_report(
    *,
    org: str,
    products: Sequence[str] = PRODUCTS,
    apply: bool = False,
    adopt_existing: Sequence[str] = (),
    run: Run | None = None,
    manifest_path: Path | str | None = None,
    repository_root: Path | str | None = None,
    personal_fn: Callable[..., dict[str, Any]] | None = None,
    ssh_fn: Callable[..., dict[str, Any]] | None = None,
    store_fn: Callable[..., dict[str, Any]] | None = None,
    codex_fn: Callable[..., dict[str, Any]] | None = None,
    cli_fn: Callable[[Path], dict[str, str]] | None = None,
    update_fn: Callable[..., tuple[dict[str, Any], int]] | None = None,
    doctor_fn: Callable[..., dict[str, Any]] | None = None,
    resolve_fn: Callable[..., dict[str, Any]] | None = None,
    commit_config_fn: Callable[..., Path] | None = None,
    personal_mirror_cleanup_fn: Callable[..., list[str]] | None = None,
    consumer_probe_fn: Callable[[Path, Path | None], dict[str, str]] | None = None,
    mirror_seed_fn: Callable[..., list[str]] | None = None,
) -> dict[str, Any]:
    """Run the resumable Admin-handoff-to-healthy-machine transaction.

    Every injectable collaborator defaults to `None` and is resolved to its
    real module-level implementation HERE, inside the function body, rather
    than as a `param: T = real_impl` default-argument value. Python binds
    default-argument values exactly once, at function-DEFINITION time (module
    import) -- so a bare `ssh_fn: ... = ensure_machine_ssh_identity` default
    captures whatever `ensure_machine_ssh_identity` pointed at when this
    module first loaded, and a later `monkeypatch.setattr(onboard_module,
    "ensure_machine_ssh_identity", fake)` -- this codebase's usual seam for
    substituting real collaborators in tests -- has no effect on any call
    that omits the keyword, since the default was already captured. Resolving
    with `if x is None: x = <module-level name>` instead performs that name
    lookup fresh on every call, so it picks up whatever the module attribute
    currently is -- letting `onboard_cmd` (which passes none of these
    keywords) still be safely monkeypatchable at the CLI level. See
    tests/test_onboard_contract.py's `TestOnboardCmdWiring` for the
    regression test that proves this holds.
    """
    if run is None:
        run = _run
    if personal_fn is None:
        personal_fn = build_personal_onboard_report
    if ssh_fn is None:
        ssh_fn = ensure_machine_ssh_identity
    if store_fn is None:
        store_fn = _provision_store
    if codex_fn is None:
        codex_fn = _install_codex_plugin
    if cli_fn is None:
        cli_fn = _sync_cli_manifest
    if update_fn is None:
        update_fn = execute_update
    if doctor_fn is None:
        doctor_fn = build_doctor_report
    if resolve_fn is None:
        resolve_fn = build_resolve_report
    if commit_config_fn is None:
        commit_config_fn = _commit_machine_pointers
    if personal_mirror_cleanup_fn is None:
        personal_mirror_cleanup_fn = _quarantine_legacy_personal_mirrors
    if consumer_probe_fn is None:
        consumer_probe_fn = _probe_cli_candidate
    if mirror_seed_fn is None:
        mirror_seed_fn = _seed_cold_start_mirrors

    normalized = tuple(dict.fromkeys(value.strip().lower() for value in products))
    org = org.strip()
    if not org or not normalized or any(value not in PRODUCTS for value in normalized):
        raise ValueError(
            "An organization and supported products (claude,codex) are required."
        )
    if org.casefold() == "auto":
        org = _discover_org(normalized, run=run)
    stages: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    # G-4 (task 207): the run-scoped completed_actions ledger. Every
    # `_ecosystem_result` call below threads this same list through, so a
    # result can only ever claim nothing changed when it is still empty --
    # never because a later exit path forgot to carry it. Nothing is
    # appended until the topology preflight gate (task 206) has already
    # passed and the first `apply=True` collaborator call actually runs.
    ledger: list[dict[str, Any]] = []
    handoff = _load_handoff(org, normalized, run=run)
    configured_components = handoff.get("components")
    if (
        not isinstance(configured_components, list)
        or not configured_components
        or any(value not in COMPONENTS for value in configured_components)
        or len(configured_components) != len(set(configured_components))
    ):
        raise RuntimeError(
            "The organization handoff does not name a supported, unique component set."
        )
    ecosystem_components = tuple(configured_components)
    missing_components = [
        component for component in COMPONENTS if component not in ecosystem_components
    ]
    if missing_components:
        raise RuntimeError(
            "The organization handoff is incomplete. It must enable Knowledge, CLI, Claude, and Codex."
        )
    stages.append({"stage": "organization-handoff", "result": "ready"})
    # Every apply begins with a complete read-only plan. No personal
    # repository, SSH config, store identity, or local manifest is mutated
    # until all adoption decisions are known to be safe.
    personal = personal_fn(
        components=ecosystem_components,
        apply=False,
        adopt_existing=adopt_existing,
        run=run,
    )
    personal_detail = next(
        (
            row.get("package_detail") or row.get("detail")
            for row in personal.get("repositories", [])
            if row.get("action") == "blocked" or row.get("package_action") == "blocked"
        ),
        None,
    )
    personal_stage = {
        "stage": "personal-packages",
        "result": personal["result"],
        "summary": personal["summary"],
    }
    if personal_detail:
        personal_stage["detail"] = personal_detail
    stages.append(personal_stage)
    inventory.extend(_personal_inventory(personal))
    if personal["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            apply,
            "blocked",
            stages,
            inventory=inventory,
            components=ecosystem_components,
            completed_actions=ledger,
        )
    department_units = _eligible_department_units(
        handoff, org, personal["owner"], run=run
    )
    legacy_injected_mode = manifest_path is not None and repository_root is None
    visible_root = (
        Path(repository_root).expanduser()
        if repository_root is not None
        else _infer_repository_root(department_units)
    )
    manifest = _layer_manifest(
        org,
        personal["owner"],
        ecosystem_components,
        handoff,
        run=run,
        department_units=department_units,
        repository_root=visible_root,
    )
    topology_layers = _topology_report_layers(manifest, run=run)
    if legacy_injected_mode:
        for row in topology_layers:
            row.update(
                local_state="legacy-test-mode",
                connection_state="planned",
                sync_state="not-checked",
                action="reuse",
                detail="Visible repository placement was not requested by this injected transaction.",
            )
    repository_stage = {
            "stage": "repository-location",
            "result": "ready" if visible_root is not None or legacy_injected_mode else "changes-required",
            "action": "reuse" if visible_root is not None or legacy_injected_mode else "choose",
            "detail": (
                f"Copilot repositories are visible in {visible_root}."
                if visible_root is not None
                else "Visible repository placement is controlled by this injected transaction."
                if legacy_injected_mode
                else "Choose the visible folder where Copilot repositories should be created or downloaded."
            ),
        }
    if visible_root is not None:
        repository_stage["path"] = str(visible_root)
    if not legacy_injected_mode:
        stages.append(repository_stage)
    if manifest_path:
        target = Path(manifest_path).expanduser()
        configured_manifest: Path | str | None = target
        legacy_manifests: tuple[Path, ...] = ()
    else:
        target = Path.home() / ".config" / "copilot" / "copilot.layers.yml"
        configured_manifest = resolve_key("layers.manifest")
        legacy_manifests = (
            Path.home() / ".copilot" / "copilot.layers.yml",
            Path.home() / ".copilot-cli" / "copilot.layers.yml",
        )
    adoption = _manifest_adoption_plan(
        manifest,
        target,
        configured_path=configured_manifest,
        legacy_paths=legacy_manifests,
        allowed_root=None if manifest_path else Path.home(),
    )
    inventory.append(adoption.as_item())
    # `github-work` is what the layer manifest above just wired every org
    # repo through; `github-personal` is what it wired every personal repo
    # through. Both are real targets an adopted alias can be proven against
    # (B1 check 4), not just a live login.
    ssh_verify_repos = {
        "github-work": f"{org}/{normalized[0]}-copilot-internal",
        "github-personal": f"{personal['owner']}/{normalized[0]}-copilot-private",
    }
    ssh = ssh_fn(
        apply=False,
        run=run,
        adopt_existing=adopt_existing,
        verify_repos=ssh_verify_repos,
    )
    stages.append({"stage": "device-ssh", **_ssh_stage_fields(ssh)})
    inventory.extend(_ssh_inventory(ssh))
    if ssh["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            apply,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )
    stages.append(
        {
            "stage": "layer-manifest",
            "result": "blocked"
            if adoption.action == "review"
            else ("ready" if adoption.action == "reuse" else "changes-required"),
            "action": adoption.action,
            "detail": adoption.detail,
            "path": str(target),
            "layers": len(adoption.payload["layers"])
            if adoption.payload
            else len(manifest["layers"]),
        }
    )
    if adoption.action == "review":
        return _ecosystem_result(
            org,
            normalized,
            apply,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )
    candidate = _validate_manifest_candidate(adoption, consumer_probe_fn)
    if candidate["result"] == "blocked":
        manifest_stage = next(
            stage for stage in stages if stage["stage"] == "layer-manifest"
        )
        manifest_stage["result"] = "blocked"
        manifest_stage["detail"] = candidate["detail"]
        return _ecosystem_result(
            org,
            normalized,
            apply,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )
    store = handoff.get("store") or {}
    store_report = store_fn(store, apply=False, run=run)
    stages.append({"stage": "secret-store", **store_report})
    if store_report["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            apply,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )
    if "codex" in normalized:
        codex_plan = codex_fn(apply=False, run=run)
        stages.append({"stage": "codex-plugin", **codex_plan})
        if codex_plan["result"] == "blocked":
            return _ecosystem_result(
                org,
                normalized,
                False,
                "blocked",
                stages,
                topology_layers,
                inventory,
                ecosystem_components,
                completed_actions=ledger,
            )
    if not apply:
        needs_change = any(
            item["action"] in {"create", "migrate", "repair"} for item in inventory
        ) or any(layer.get("action") != "reuse" for layer in topology_layers)
        return _ecosystem_result(
            org,
            normalized,
            False,
            "changes-required" if needs_change else "ready",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    if visible_root is None and not legacy_injected_mode:
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    # G-3 (task 206): `topology_layers` was already closed above by
    # `_topology_report_layers`, which runs `_classify_repository_history` --
    # history, origin-URL, and local-path-conflict verdicts -- for every
    # visible layer. That verdict is deterministic and entirely read-only, so
    # any blocking (`review`/`choose-location`) row must stop the run HERE,
    # before `personal_fn`/`ssh_fn` are ever invoked with `apply=True` and
    # reach out to create a GitHub repository or register a device SSH key.
    # Previously this same verdict was only acted on inside
    # `_apply_visible_topology`, called after both of those irreversible
    # remote writes -- exactly how a run created orphaned Personal
    # repositories on GitHub and only then blocked on a fully deterministic
    # Git-ancestry condition it could have checked first. `_apply_visible_topology`
    # still carries its own `review`/`choose-location` guard as defense-in-depth;
    # it should now be unreachable except by a state change between here and
    # its own read of these same rows.
    if not legacy_injected_mode:
        blocking_layer = next(
            (
                row
                for row in topology_layers
                if row["action"] in {"review", "choose-location"}
            ),
            None,
        )
        if blocking_layer is not None:
            stages.append(
                {
                    "stage": "visible-repositories",
                    "result": "blocked",
                    "detail": blocking_layer["detail"],
                    "path": str(visible_root),
                    "layers": len(topology_layers),
                }
            )
            return _ecosystem_result(
                org,
                normalized,
                True,
                "blocked",
                stages,
                topology_layers,
                inventory,
                ecosystem_components,
                completed_actions=ledger,
            )

    personal = personal_fn(
        components=ecosystem_components,
        apply=True,
        adopt_existing=adopt_existing,
        run=run,
    )
    personal_stage = next(
        stage for stage in stages if stage["stage"] == "personal-packages"
    )
    personal_stage.update(result=personal["result"], summary=personal["summary"])
    # G-4 (task 207): record every Personal GitHub mutation this call just
    # made -- created repository, seeded/adopted package marker -- BEFORE
    # checking whether it blocked, so a block here still emits an honest,
    # populated ledger rather than looking indistinguishable from the
    # pre-write blocks above.
    ledger.extend(_personal_ledger_entries(personal))
    if personal["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    ssh = ssh_fn(
        apply=True,
        run=run,
        adopt_existing=adopt_existing,
        verify_repos=ssh_verify_repos,
    )
    ssh_stage = next(stage for stage in stages if stage["stage"] == "device-ssh")
    ssh_stage.update(_ssh_stage_fields(ssh))
    ledger.extend(_ssh_ledger_entries(ssh))
    if ssh["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    if legacy_injected_mode:
        topology_ok, topology_detail = True, None
    else:
        topology_ok, topology_detail = _apply_visible_topology(
            manifest, topology_layers, run=run
        )
        # Drain every row's recorded mutation into the ledger regardless of
        # `topology_ok` -- a blocking row further down the (reverse-ranked)
        # list does not undo the repositories `_apply_visible_topology`
        # already placed or fast-forwarded for the rows before it.
        for topology_row in topology_layers:
            row_entries = topology_row.pop("_ledger_entries", None)
            if row_entries:
                ledger.extend(row_entries)
        stages.append({
            "stage": "visible-repositories",
            "result": "ready" if topology_ok else "blocked",
            "detail": topology_detail
            or f"All {len(topology_layers)} expected repositories are visible in {visible_root}.",
            "path": str(visible_root),
            "layers": len(topology_layers),
        })
    if not topology_ok:
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    store_report = store_fn(store, apply=True, run=run)
    store_stage = next(stage for stage in stages if stage["stage"] == "secret-store")
    store_stage.update(store_report)
    if store_report["result"] == "blocked":
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    backup = _apply_manifest_adoption(adoption)
    manifest_stage = next(
        stage for stage in stages if stage["stage"] == "layer-manifest"
    )
    manifest_stage["result"] = "reused" if adoption.action == "reuse" else "applied"
    if backup is not None:
        manifest_stage["rollback_path"] = str(backup)
    # G-4 (task 207): `_apply_manifest_adoption` returns `None` without
    # writing anything when `adoption.action == "reuse"` -- there is nothing
    # to ledger in that case. Otherwise this is the one write
    # `blocked_after_write` below is ever allowed to compensate for
    # (never-destroy: a created GitHub repository or registered device key
    # is never rolled back), so it is the only ledger entry whose recorded
    # `outcome` can still change after it is first appended.
    manifest_ledger_entry: dict[str, Any] | None = None
    if adoption.action != "reuse":
        manifest_ledger_entry = _ledger_entry(
            kind="layer-manifest",
            target=str(target),
            outcome="completed",
            summary=f"Wrote the layer manifest to {target}.",
            backup_path=str(backup) if backup is not None else None,
        )
        ledger.append(manifest_ledger_entry)

    def blocked_after_write(detail: str) -> dict[str, Any]:
        # G-9 (task 215 blocker fix): rollback CONFIRMATION is a pure byte
        # comparison, never a re-run of the materialize/policy gates.
        # `_rollback_manifest_adoption` above already proves the manifest
        # FILE was restored (or removed) to its exact pre-transaction bytes
        # -- reading back `plan.destination`/`plan.source` and comparing
        # against `backup`'s bytes -- before it ever returns `True`; nothing
        # below may downgrade that to "rollback-failed" just because a
        # LATER, separate reconciliation pass's own fail-closed materialize
        # gates report `held`/`blocked` for the RESTORED (old) manifest's
        # own content. That was the live incident's exact conflation: the
        # file was verifiably restored byte-identical, yet the stage
        # self-reported "rollback-failed" because the confirmation re-ran
        # the same gates the restored manifest's own content still (validly)
        # trips. A `held`/`blocked` verdict is an honest per-item outcome of
        # the gate, never evidence the file rollback itself failed.
        rolled_back = _rollback_manifest_adoption(adoption, backup)
        prior_manifest = adoption.source
        reconcile_note = ""
        if (
            rolled_back
            and prior_manifest is not None
            and prior_manifest.is_file()
            and adoption.action != "reuse"
        ):
            # Best-effort machine reconciliation: fold back out anything the
            # failed candidate already materialized so the restored (old)
            # manifest's own machine content stays honest, mirroring the
            # main materialize gate below. Its own result is reported, but
            # -- like that gate -- only a genuine environment failure (an
            # exception, or an exit code outside 0/1) is worth surfacing;
            # `held`/`blocked` (exit 1) is that content's own honest,
            # unrelated state, never proof the FILE rollback (already
            # byte-confirmed above) failed.
            try:
                _, restore_exit = update_fn(
                    dry_run=False, _manifest_path=prior_manifest
                )
                if restore_exit not in (0, 1):
                    reconcile_note = (
                        " The restored manifest's own machine reconciliation "
                        "could not be confirmed; run `cc update` to finish "
                        "reconciling it."
                    )
            except Exception as exc:
                reconcile_note = (
                    " The restored manifest's own machine reconciliation "
                    f"failed: {exc}"
                )
            try:
                cli_fn(prior_manifest)
            except Exception as exc:
                reconcile_note += f" CLI layer sync could not be reconciled: {exc}"
        manifest_stage["result"] = "rolled-back" if rolled_back else "rollback-failed"
        manifest_stage["detail"] = (
            f"{detail} The previous manifest was restored.{reconcile_note}"
            if rolled_back
            else (
                f"{detail} Automatic rollback could not be proven complete; "
                f"use {backup} to recover before continuing."
                if backup is not None
                else f"{detail} Automatic rollback could not be proven complete."
            )
        )
        if manifest_ledger_entry is not None:
            # Never omitted -- only ever relabeled. A successful rollback is
            # the one case in this whole ledger where a `completed` mutation
            # is allowed to become something other than permanent.
            manifest_ledger_entry["outcome"] = (
                "rolled-back" if rolled_back else "completed"
            )
            manifest_ledger_entry["summary"] = manifest_stage["detail"]
        return _ecosystem_result(
            org,
            normalized,
            True,
            "blocked",
            stages,
            topology_layers,
            inventory,
            ecosystem_components,
            completed_actions=ledger,
        )

    try:
        update, update_exit = update_fn(dry_run=False, _manifest_path=target)
    except Exception as exc:
        return blocked_after_write(f"Materialization failed: {exc}")
    materialize_result = update.get("result", "blocked")
    materialize_held_items = update.get("held_for_approval", [])
    materialize_blocked_items = update.get("blocked", [])
    stages.append(
        {
            "stage": "materialize",
            "result": materialize_result,
            "blocked": len(materialize_blocked_items),
            "held": len(materialize_held_items),
        }
    )
    # G-9 (task 215 blocker fix): topology is already verified and the
    # manifest is already written above -- from here on, only a materialize
    # failure that is TOTAL and unexpected invalidates that write. Per
    # `update.py`'s own `compute_exit_code` contract, exit 0 is
    # applied/up-to-date and exit 1 is held/blocked -- both are the
    # materialize engine running to completion and reporting an HONEST
    # per-item outcome (a never-destroy guard refusing to overwrite
    # protected content, or the fail-closed signature policy refusing
    # unverified content). Neither is corruption, and neither may roll back
    # topology this run already verified. Only an exit code outside {0, 1}
    # (an environment-level failure -- lock contention, an invalid
    # manifest -- see `compute_exit_code`'s docstring) reaches here, besides
    # the exception case already handled above.
    if update_exit not in (0, 1):
        return blocked_after_write(
            "Materialization failed for an environment reason, not a per-item policy hold or block."
        )
    ledger.append(
        _ledger_entry(
            kind="materialization",
            target=str(target),
            outcome="completed",
            summary=(
                f"Materialized the local Copilot layer mirrors described by {target}."
                if materialize_result in ("applied", "up-to-date")
                else (
                    f"Materialized what the fail-closed signature policy and "
                    f"never-destroy guard currently allow from {target}: "
                    f"{len(materialize_held_items)} item(s) held for approval, "
                    f"{len(materialize_blocked_items)} item(s) unverified. "
                    "Neither stops this transaction -- see the `materialize` "
                    "field for the honest per-item detail."
                )
            ),
        )
    )
    try:
        cli_report = cli_fn(target)
    except Exception as exc:
        return blocked_after_write(f"CLI layer sync failed: {exc}")
    stages.append({"stage": "cli-sync", **cli_report})
    if cli_report.get("result") != "ready":
        return blocked_after_write(
            cli_report.get("detail", "CLI layer sync rejected the candidate manifest.")
        )
    if "codex" in normalized:
        try:
            codex_report = codex_fn(apply=True, run=run)
        except Exception as exc:
            return blocked_after_write(f"Codex activation failed: {exc}")
        next(stage for stage in stages if stage["stage"] == "codex-plugin").update(
            codex_report
        )
        if codex_report["result"] == "blocked":
            return blocked_after_write(
                "Codex activation rejected the candidate layer manifest."
            )
    # G-10 (task 215, second blocker fix): best-effort, never-fatal seeding
    # of the read-only mirror clone for any layer whose first-ever
    # appearance in a manifest this doctor ladder checks would otherwise
    # only ever see cold start -- see `_seed_cold_start_mirrors`'s own
    # docstring. A collaborator failure here (a bad test double, or a
    # genuinely misbehaving injected function) never blocks the
    # already-verified manifest write below; `_seed_cold_start_mirrors`
    # itself already degrades every real network/offline failure to an
    # honest no-op, so this `except` exists only for the collaborator
    # contract, not for anything network-shaped.
    seeded_mirrors: list[str] = []
    if not legacy_injected_mode:
        try:
            seeded_mirrors = mirror_seed_fn(manifest)
        except Exception:
            seeded_mirrors = []
        for layer_id in seeded_mirrors:
            ledger.append(
                _ledger_entry(
                    kind="mirror-seed",
                    target=layer_id,
                    outcome="completed",
                    summary=(
                        f"Seeded a first-time read-only mirror clone for {layer_id} so "
                        "its health check has a real local revision to verify, not just "
                        "an unpublished freshness pointer."
                    ),
                )
            )

    try:
        doctor = doctor_fn(_manifest_path=target)
    except Exception as exc:
        return blocked_after_write(f"The post-apply health check failed: {exc}")
    doctor_checkers = doctor.get("checkers") or []
    doctor_fail_count = sum(
        1 for c in doctor_checkers if isinstance(c, dict) and c.get("severity") == "fail"
    )
    doctor_warn_count = sum(
        1 for c in doctor_checkers if isinstance(c, dict) and c.get("severity") == "warn"
    )
    doctor_stage: dict[str, Any] = {
        "stage": "doctor",
        "result": doctor.get("status", "unknown"),
        "score": doctor.get("score"),
    }
    if doctor_checkers or seeded_mirrors:
        detail_parts = []
        if seeded_mirrors:
            detail_parts.append(
                f"Seeded {len(seeded_mirrors)} first-time mirror clone(s) before this check."
            )
        detail_parts.append(
            f"{doctor_fail_count} checker(s) failed, {doctor_warn_count} reported a "
            "warning -- only a failure can undo this manifest write."
        )
        doctor_stage["detail"] = " ".join(detail_parts)
    stages.append(doctor_stage)
    # G-10 (task 215, second blocker fix): only a real FAIL-severity checker
    # -- corruption, a missing path, a signature failure -- invalidates the
    # topology this run already verified byte-for-byte above. A layer's
    # FIRST appearance in ANY manifest this doctor ladder has ever checked
    # can never have a pre-existing published freshness pointer
    # (`refs/copilot/lock`) or local mirror; that is cold start, not
    # corruption, and `core/ecosystem/component_status.py`'s own contract
    # ("This module never emits `severity: fail`") guarantees a sync gap
    # always reports `warn`. Rolling back a byte-verified write on an
    # honest warn -- including the aggregate `status: offline` this
    # produces -- made first-time adoption of ANY new layer structurally
    # impossible. `status` is still surfaced above exactly as doctor
    # reported it; it no longer gates whether this write survives.
    if doctor_fail_count:
        return blocked_after_write(
            "The post-apply health check found a real failure, not just an honest warning."
        )
    if not legacy_injected_mode:
        try:
            resolution = resolve_fn(_manifest_path=target)
        except Exception as exc:
            return blocked_after_write(f"The post-apply resolution check failed: {exc}")
        resolved_items = resolution.get("items", [])
        stages.append(
            {
                "stage": "resolve",
                "result": "ready" if resolved_items else "blocked",
                "layers": len(resolved_items),
                "detail": (
                    f"Resolved {len(resolved_items)} effective Copilot capabilities."
                    if resolved_items
                    else "No effective Copilot capabilities resolved from the candidate topology."
                ),
            }
        )
        if not resolved_items:
            return blocked_after_write(
                "The candidate topology did not resolve any effective Copilot capabilities."
            )
    try:
        knowledge_paths = [
            str(Path(layer["source"]["path"]).expanduser())
            for layer in sorted(manifest["layers"], key=lambda item: item["rank"])
            if layer.get("product") == "knowledge" and layer.get("source", {}).get("path")
        ]
        if visible_root is None:
            commit_config_fn(target, _knowledge_mirror_paths(manifest))
        else:
            commit_config_fn(target, knowledge_paths, visible_root)
    except Exception as exc:
        return blocked_after_write(
            f"The ecosystem pointers could not be committed: {exc}"
        )
    if not legacy_injected_mode:
        try:
            moved_personal = personal_mirror_cleanup_fn(manifest)
        except Exception as exc:
            return blocked_after_write(
                f"Legacy hidden Personal repositories could not be quarantined: {exc}"
            )
        stages.append(
            {
                "stage": "personal-repository-location",
                "result": "ready",
                "layers": len(moved_personal),
                "detail": (
                    "Superseded hidden Personal repositories were moved to a recoverable legacy location."
                    if moved_personal
                    else "No hidden Personal repositories remain in the active mirror location."
                ),
            }
        )
    return _ecosystem_result(
        org,
        normalized,
        True,
        "ready",
        stages,
        _topology_report_layers(manifest, run=run, verified=True),
        inventory,
        ecosystem_components,
        completed_actions=ledger,
        materialize=_materialize_summary(update),
    )


def onboard_cmd(
    scope: str = typer.Option(
        "personal", "--scope", help="Repository scope; currently personal."
    ),
    components: str = typer.Option(
        ",".join(COMPONENTS),
        "--components",
        help="Comma-separated ecosystem components.",
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Create confirmed-missing private repositories."
    ),
    output_json: bool = typer.Option(
        False, "--json", help="Emit the versioned onboarding report."
    ),
    org: str | None = typer.Option(
        None, "--org", help="Organization slug for the complete ecosystem transaction."
    ),
    products: str = typer.Option(
        ",".join(PRODUCTS), "--products", help="Comma-separated Copilot products."
    ),
    adopt_existing: str = typer.Option(
        "",
        "--adopt-existing",
        help=(
            "Comma-separated components (or `ssh`, for the device's existing "
            "GitHub SSH alias) whose existing content the person consented to "
            "include (B1). Scoped per item: each is decided on its own, never "
            "all-or-nothing. Any adoptable item left out of this list is a no-op."
        ),
    ),
    repository_root: str | None = typer.Option(
        None,
        "--repository-root",
        help=(
            "Visible folder where ecosystem repositories are kept. When omitted, "
            "cc uses the saved folder or a single unambiguous match inside approved project roots."
        ),
    ),
) -> None:
    """Discover personal repositories, then optionally create confirmed-missing ones."""
    adopt_components = tuple(
        value.strip() for value in adopt_existing.split(",") if value.strip()
    )
    if org:
        try:
            report = build_ecosystem_onboard_report(
                org=org,
                products=products.split(","),
                apply=apply,
                adopt_existing=adopt_components,
                repository_root=repository_root,
            )
        except (RuntimeError, ValueError) as exc:
            if output_json:
                typer.echo(
                    json.dumps(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "error": {
                                "code": "onboard-unavailable",
                                "message": str(exc),
                            },
                        }
                    )
                )
            else:
                typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        typer.echo(
            json.dumps(report)
            if output_json
            else f"{report['result']}: {report['org']}"
        )
        if report["result"] == "blocked":
            raise typer.Exit(1)
        return
    if scope != "personal":
        message = "Only personal onboarding is available from the user CLI."
        if output_json:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "error": {"code": "unsupported-scope", "message": message},
                    }
                )
            )
        raise typer.Exit(2)
    try:
        report = build_personal_onboard_report(
            components=components.split(","),
            apply=apply,
            adopt_existing=adopt_components,
        )
    except (RuntimeError, ValueError) as exc:
        if output_json:
            typer.echo(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "error": {"code": "onboard-unavailable", "message": str(exc)},
                    }
                )
            )
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        json.dumps(report) if output_json else f"{report['result']}: {report['owner']}"
    )
    if report["result"] == "blocked":
        raise typer.Exit(1)
