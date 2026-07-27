"""Fail-closed repository discovery and provisioning for desktop onboarding."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit

import typer
import yaml

from cc.commands.doctor import build_doctor_report
from cc.commands.update import execute_update
from cc.core import authstore, keychain
from cc.core.config import resolve_key, write_config
from cc.core.ecosystem.manifest import ManifestError, validate_layers
from cc.core.ecosystem.ssh_identity import ensure_machine_ssh_identity

SCHEMA_VERSION = "1.0"
COMPONENTS = ("knowledge", "cli", "claude", "codex")
PRODUCTS = ("claude", "codex")
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
    "claude": (),
    "codex": (),
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
    executable = shutil.which(args[0])
    if executable is None:
        return subprocess.CompletedProcess(
            args, 127, "", f"{args[0]} is not installed."
        )
    resolved = str(Path(executable).resolve())
    environment = None
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
            environment = os.environ.copy()
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
    org: str, owner: str, products: Sequence[str], handoff: dict[str, Any], *, run: Run
) -> dict[str, Any]:
    refs = (handoff.get("foundation") or {}).get("refs") or {}
    layers: list[dict[str, Any]] = []
    for product in products:
        requested = refs.get(product)
        if not isinstance(requested, str) or not requested:
            raise RuntimeError(
                f"The organization handoff is missing foundation.refs.{product}."
            )
        exact_ref = _resolve_foundation_ref(product, requested, run=run)
        for layer_id, role, rank, repo, ref, auth in (
            (
                f"{product}-personal",
                "personal",
                10,
                f"git@github-personal:{owner}/{product}-copilot-private.git",
                "main",
                "personal",
            ),
            (
                f"{product}-organization",
                "organization",
                30,
                f"git@github-work:{org}/{product}-copilot-internal.git",
                "main",
                "work",
            ),
            (
                f"{product}-foundation",
                "foundation",
                40,
                f"https://github.com/Everyone-Needs-A-Copilot/{product}-copilot.git",
                exact_ref,
                "anon",
            ),
        ):
            source: dict[str, str] = {"repo": repo, "ref": ref}
            if product == "claude" and role == "foundation":
                source["subpath"] = ".claude"
            layers.append(
                {
                    "id": layer_id,
                    "role": role,
                    "rank": rank,
                    "product": product,
                    "source": source,
                    "auth": auth,
                    "activation": "always",
                    "policy": {
                        "allowed_signers": list(FOUNDATION_ALLOWED_SIGNERS[product])
                        if role == "foundation"
                        else []
                    },
                }
            )
    return {"version": 1, "org": org, "layers": layers}


def _atomic_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, encoding="utf-8"
    ) as handle:
        handle.write(yaml.safe_dump(payload, sort_keys=False))
        temp = Path(handle.name)
    os.replace(temp, path)


def _normalized_existing_manifest(path: Path) -> dict[str, Any]:
    """Load a supported manifest and translate the retired component key.

    The first CLI inheritance release called the product discriminator
    ``component``. It is a deterministic predecessor of ``product`` and can
    therefore be adopted without interpreting user-authored content. Any
    other structural difference remains a hold for review.
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
        layer = dict(raw_layer)
        component = layer.pop("component", None)
        product = layer.get("product")
        if product is None and isinstance(component, str) and component:
            layer["product"] = component
        elif component is not None and component != product:
            raise ManifestError(
                "The existing layer manifest disagrees about a layer's product."
            )
        layer.setdefault("activation", "always")
        if not _safe_repository_reference((layer.get("source") or {}).get("repo")):
            raise ManifestError(
                "The existing layer manifest contains an unsafe repository reference."
            )
        normalized.append(layer)
    validate_layers(normalized)
    result: dict[str, Any] = {"version": 1, "layers": normalized}
    if isinstance(raw.get("org"), str) and raw["org"]:
        result["org"] = raw["org"]
    return result


def _managed_product_is_compatible(
    existing: list[dict[str, Any]], desired: list[dict[str, Any]]
) -> bool:
    """Return true only for a previously generated stack we can repair."""
    if not existing:
        return False
    desired_by_id = {layer["id"]: layer for layer in desired}
    if not {layer.get("id") for layer in existing} <= set(desired_by_id):
        return False
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
        expected = desired_by_id[layer["id"]]
        if set(layer) - allowed_keys:
            return False
        if any(
            layer.get(key) != expected.get(key)
            for key in ("role", "rank", "product", "unit")
        ):
            return False
        actual_source = layer.get("source") or {}
        expected_source = expected.get("source") or {}
        if actual_source.get("repo") != expected_source.get("repo"):
            return False
        if actual_source.get("subpath") != expected_source.get("subpath"):
            return False
        if expected["role"] != "foundation" and actual_source.get(
            "ref"
        ) != expected_source.get("ref"):
            return False
        actual_auth, expected_auth = layer.get("auth"), expected.get("auth")
        if not any({actual_auth, expected_auth} <= group for group in auth_equivalents):
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
        existing = _normalized_existing_manifest(source)
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
        layer
        for layer in existing["layers"]
        if layer["product"] not in desired_products
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

    merged = {
        "version": 1,
        "org": desired.get("org"),
        "layers": [*retained, *desired_layers],
    }
    try:
        validate_layers(merged["layers"])
    except ManifestError:
        return ManifestAdoption(
            "conflict",
            "review",
            "The existing and planned layers cannot be combined safely. Nothing will be replaced.",
            source,
            destination,
            None,
        )

    if source == destination and existing == merged:
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


def _provision_store(store: dict[str, Any], *, apply: bool, run: Run) -> dict[str, Any]:
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
    args = [
        "copilot",
        "infisical",
        "--json",
        "identity",
        "provision",
        "--project",
        store["workspace_id"],
        "--environment",
        store["environment"],
        "--secret-path",
        store["secret_path"],
    ]
    if apply:
        args.append("--apply")
    result = run(tuple(args))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "result": "blocked",
            "detail": "The secret-store provisioner returned an unreadable response.",
        }
    if result.returncode != 0 or payload.get("result") == "blocked":
        return {
            "result": "blocked",
            "detail": payload.get(
                "detail", "The secret-store identity could not be provisioned."
            ),
        }
    return {
        "result": payload.get("result", "ready"),
        "type": "infisical",
        "scope": payload.get("scope"),
    }


def _install_codex_plugin(*, apply: bool, run: Run) -> dict[str, Any]:
    root = Path(str(resolve_key("paths.codex_materialize_root"))).expanduser()
    plugin = root / "plugins" / "codex-copilot"
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    if not apply:
        ready = (
            plugin.joinpath(".codex-plugin", "plugin.json").is_file()
            and marketplace.is_file()
        )
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
            "detail": "Codex could not register the verified local marketplace.",
        }
    installed = run(
        ("codex", "plugin", "add", "codex-copilot@enac-materialized", "--json")
    )
    if installed.returncode != 0:
        return {
            "result": "blocked",
            "detail": "Codex could not install Codex Copilot from the verified marketplace.",
        }
    return {"result": "ready"}


def _ecosystem_result(
    org: str,
    products: Sequence[str],
    apply: bool,
    result: str,
    stages: list[dict[str, Any]],
    layers: Sequence[dict[str, Any]] | None = None,
    inventory: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = {
        "schema_version": SCHEMA_VERSION,
        "scope": "ecosystem",
        "mode": "apply" if apply else "plan",
        "result": result,
        "org": org,
        "products": list(products),
        "stages": stages,
    }
    report["layers"] = [
        {
            "id": layer["id"],
            "product": layer["product"],
            "role": layer["role"],
            "rank": layer["rank"],
        }
        for layer in (layers or ())
    ]
    report["inventory"] = list(inventory or ())
    report["inventory_summary"] = {
        "reused": sum(item.get("action") == "reuse" for item in report["inventory"]),
        "changes": sum(
            item.get("action") in {"create", "migrate", "repair"}
            for item in report["inventory"]
        ),
        "review": sum(item.get("action") == "review" for item in report["inventory"]),
    }
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
    personal_fn: Callable[..., dict[str, Any]] | None = None,
    ssh_fn: Callable[..., dict[str, Any]] | None = None,
    store_fn: Callable[..., dict[str, Any]] | None = None,
    codex_fn: Callable[..., dict[str, Any]] | None = None,
    update_fn: Callable[..., tuple[dict[str, Any], int]] | None = None,
    doctor_fn: Callable[..., dict[str, Any]] | None = None,
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
    if update_fn is None:
        update_fn = execute_update
    if doctor_fn is None:
        doctor_fn = build_doctor_report

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
    handoff = _load_handoff(org, normalized, run=run)
    stages.append({"stage": "organization-handoff", "result": "ready"})
    # Every apply begins with a complete read-only plan. No personal
    # repository, SSH config, store identity, or local manifest is mutated
    # until all adoption decisions are known to be safe.
    personal = personal_fn(
        components=normalized, apply=False, adopt_existing=adopt_existing, run=run
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
            org, normalized, apply, "blocked", stages, inventory=inventory
        )
    manifest = _layer_manifest(org, personal["owner"], normalized, handoff, run=run)
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
        apply=False, run=run, adopt_existing=adopt_existing, verify_repos=ssh_verify_repos
    )
    stages.append({"stage": "device-ssh", **_ssh_stage_fields(ssh)})
    inventory.extend(_ssh_inventory(ssh))
    if ssh["result"] == "blocked":
        return _ecosystem_result(
            org, normalized, apply, "blocked", stages, manifest["layers"], inventory
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
            org, normalized, apply, "blocked", stages, manifest["layers"], inventory
        )
    store = handoff.get("store") or {}
    store_report = store_fn(store, apply=False, run=run)
    stages.append({"stage": "secret-store", **store_report})
    if store_report["result"] == "blocked":
        return _ecosystem_result(
            org, normalized, apply, "blocked", stages, manifest["layers"], inventory
        )
    if "codex" in normalized:
        codex_plan = codex_fn(apply=False, run=run)
        stages.append({"stage": "codex-plugin", **codex_plan})
    if not apply:
        needs_change = any(
            item["action"] in {"create", "migrate", "repair"} for item in inventory
        )
        return _ecosystem_result(
            org,
            normalized,
            False,
            "changes-required" if needs_change else "ready",
            stages,
            manifest["layers"],
            inventory,
        )

    personal = personal_fn(
        components=normalized, apply=True, adopt_existing=adopt_existing, run=run
    )
    personal_stage = next(
        stage for stage in stages if stage["stage"] == "personal-packages"
    )
    personal_stage.update(result=personal["result"], summary=personal["summary"])
    if personal["result"] == "blocked":
        return _ecosystem_result(
            org, normalized, True, "blocked", stages, manifest["layers"], inventory
        )

    ssh = ssh_fn(
        apply=True, run=run, adopt_existing=adopt_existing, verify_repos=ssh_verify_repos
    )
    ssh_stage = next(stage for stage in stages if stage["stage"] == "device-ssh")
    ssh_stage.update(_ssh_stage_fields(ssh))
    if ssh["result"] == "blocked":
        return _ecosystem_result(
            org, normalized, True, "blocked", stages, manifest["layers"], inventory
        )

    store_report = store_fn(store, apply=True, run=run)
    store_stage = next(stage for stage in stages if stage["stage"] == "secret-store")
    store_stage.update(store_report)
    if store_report["result"] == "blocked":
        return _ecosystem_result(
            org, normalized, True, "blocked", stages, manifest["layers"], inventory
        )

    backup = _apply_manifest_adoption(adoption)
    write_config("layers.manifest", str(target))
    manifest_stage = next(
        stage for stage in stages if stage["stage"] == "layer-manifest"
    )
    manifest_stage["result"] = "reused" if adoption.action == "reuse" else "applied"
    if backup is not None:
        manifest_stage["rollback_path"] = str(backup)
    update, update_exit = update_fn(dry_run=False)
    stages.append(
        {
            "stage": "materialize",
            "result": update.get("result", "blocked"),
            "blocked": len(update.get("blocked", [])),
            "held": len(update.get("held_for_approval", [])),
        }
    )
    if update_exit == 0 and "codex" in normalized:
        codex_report = codex_fn(apply=True, run=run)
        next(stage for stage in stages if stage["stage"] == "codex-plugin").update(
            codex_report
        )
        if codex_report["result"] == "blocked":
            return _ecosystem_result(
                org, normalized, True, "blocked", stages, manifest["layers"], inventory
            )
    doctor = doctor_fn()
    stages.append(
        {
            "stage": "doctor",
            "result": doctor.get("status", "unknown"),
            "score": doctor.get("score"),
        }
    )
    result = (
        "ready" if update_exit == 0 and doctor.get("status") == "healthy" else "blocked"
    )
    return _ecosystem_result(
        org, normalized, True, result, stages, manifest["layers"], inventory
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
