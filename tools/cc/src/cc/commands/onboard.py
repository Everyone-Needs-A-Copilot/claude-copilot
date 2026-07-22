"""Fail-closed repository discovery and provisioning for desktop onboarding."""

from __future__ import annotations

import json
import base64
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import typer
import yaml

from cc.commands.doctor import build_doctor_report
from cc.commands.update import execute_update
from cc.core.config import resolve_key, write_config
from cc.core.ecosystem.ssh_identity import ensure_machine_ssh_identity

SCHEMA_VERSION = "1.0"
COMPONENTS = ("knowledge", "cli", "claude", "codex")
PRODUCTS = ("claude", "codex")
Run = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class Probe:
    state: str
    visibility: str | None
    detail: str


@dataclass(frozen=True)
class PackageProbe:
    state: str
    detail: str


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if not args:
        return subprocess.CompletedProcess(args, 127, "", "No command was provided.")
    executable = shutil.which(args[0])
    if executable is None:
        return subprocess.CompletedProcess(args, 127, "", f"{args[0]} is not installed.")
    resolved = str(Path(executable).resolve())
    return subprocess.run((resolved, *args[1:]), capture_output=True, text=True, check=False)


def _probe(owner: str, name: str, *, run: Run) -> Probe:
    result = run(("gh", "api", f"repos/{owner}/{name}"))
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
            private = payload["private"]
            if not isinstance(private, bool):
                raise ValueError("private is not boolean")
        except (json.JSONDecodeError, KeyError, ValueError):
            return Probe("unknown", None, "GitHub returned an unreadable repository response.")
        if private:
            return Probe("existing-private", "private", "Existing private repository will be reused.")
        return Probe("conflict-public", "public", "A public repository already uses this name.")

    if "HTTP 404" in result.stderr:
        return Probe("missing", None, "Repository does not exist and can be created privately.")
    return Probe("unknown", None, "GitHub could not confirm whether this repository exists.")


def _owner(*, run: Run) -> str:
    result = run(("gh", "api", "user", "--jq", ".login"))
    owner = result.stdout.strip()
    if result.returncode != 0 or not owner:
        raise RuntimeError("GitHub could not confirm the authenticated personal account.")
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
            return PackageProbe("ready", "Existing rank-10 package will be reused.")
        return PackageProbe("held", "Existing package manifest is unfamiliar or invalid; nothing will be replaced.")
    if not _is_404(manifest):
        return PackageProbe("unknown", "GitHub could not verify the existing package manifest.")

    contents = run(("gh", "api", f"repos/{owner}/{name}/contents"))
    if _is_404(contents):
        # GitHub returns 404 for the root contents endpoint when a repository
        # has no commits. The repository itself was already confirmed private.
        return PackageProbe("empty", "Confirmed-empty private repository can receive the rank-10 seed.")
    if contents.returncode != 0:
        return PackageProbe("unknown", "GitHub could not confirm whether the private repository is empty.")
    try:
        root = json.loads(contents.stdout)
    except json.JSONDecodeError:
        return PackageProbe("unknown", "GitHub returned an unreadable repository contents response.")
    if isinstance(root, list) and not root:
        return PackageProbe("empty", "Confirmed-empty private repository can receive the rank-10 seed.")
    return PackageProbe("held", "Existing user content has no recognized package manifest; nothing will be inferred or replaced.")


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
    encoded = base64.b64encode(_personal_seed(component).encode("utf-8")).decode("ascii")
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


def _row(component: str, owner: str, probe: Probe, package: PackageProbe | None) -> dict[str, Any]:
    package_state = package.state if package else ("missing" if probe.state == "missing" else "unknown")
    package_action = "seed" if package_state in {"missing", "empty"} else (
        "none" if package_state == "ready" else "blocked"
    )
    return {
        "component": component,
        "role": "personal",
        "unit": None,
        "owner": owner,
        "name": f"{component}-copilot-private",
        "visibility": probe.visibility,
        "state": probe.state,
        "action": "create" if probe.state == "missing" else ("none" if probe.state == "existing-private" and package_action != "blocked" else "blocked"),
        "detail": probe.detail,
        "rank": 10,
        "package_state": package_state,
        "package_action": package_action,
        "package_detail": package.detail if package else "Rank-10 package will be initialized after creation.",
    }


def _report(owner: str, mode: str, rows: list[dict[str, Any]], result: str) -> dict[str, Any]:
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
            "blocked": sum(row["action"] == "blocked" for row in rows),
        },
    }


def build_personal_onboard_report(
    *, components: Sequence[str] = COMPONENTS, apply: bool = False, run: Run = _run
) -> dict[str, Any]:
    """Plan or apply personal repositories. Apply always repeats the full probe."""
    normalized = tuple(dict.fromkeys(component.strip().lower() for component in components))
    invalid = [component for component in normalized if component not in COMPONENTS]
    if not normalized or invalid:
        raise ValueError(f"Unsupported components: {', '.join(invalid) or 'none'}")

    owner = _owner(run=run)
    rows = []
    for component in normalized:
        name = f"{component}-copilot-private"
        probe = _probe(owner, name, run=run)
        package = _probe_package(owner, name, component, run=run) if probe.state == "existing-private" else None
        rows.append(_row(component, owner, probe, package))
    blocked = any(row["action"] == "blocked" for row in rows)
    if blocked:
        return _report(owner, "apply" if apply else "plan", rows, "blocked")
    if not apply:
        needs_change = any(
            row["state"] == "missing" or row["package_state"] == "empty" for row in rows
        )
        return _report(owner, "plan", rows, "changes-required" if needs_change else "ready")

    for row in rows:
        if row["state"] != "missing":
            continue
        created = run(
            (
                "gh", "api", "-X", "POST", "user/repos",
                "-f", f"name={row['name']}", "-F", "private=true", "-F", "auto_init=false",
                "-f", f"description=Private personal layer for {row['component'].title()} Copilot",
            )
        )
        if created.returncode == 0:
            row.update(state="created", visibility="private", action="none", detail="Created private repository.")
            row["package_state"] = "empty"
        else:
            row.update(state="unknown", action="blocked", detail="GitHub did not confirm repository creation.")
            return _report(owner, "apply", rows, "blocked")
    for row in rows:
        if row["package_state"] != "empty":
            continue
        if _seed_package(owner, row["name"], row["component"], run=run):
            row.update(
                package_state="seeded",
                package_action="none",
                package_detail="Initialized the minimal rank-10 package in the confirmed-empty repository.",
            )
        else:
            row.update(
                package_state="unknown",
                package_action="blocked",
                action="blocked",
                package_detail="GitHub did not confirm rank-10 package initialization.",
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
            raise RuntimeError(f"{org}/{repo}/ecosystem.yml is not a supported v2 handoff.")
        if handoff.get("org") != org:
            raise RuntimeError(f"{org}/{repo}/ecosystem.yml names a different organization.")
        if not isinstance(configured, list) or any(value not in configured for value in products):
            raise RuntimeError("The organization handoff does not enable every requested Copilot product.")
        return handoff
    raise RuntimeError(errors[0] if errors else "No organization handoff repository was selected.")


def _discover_org(products: Sequence[str], *, run: Run) -> str:
    result = run(("gh", "api", "user/orgs", "--paginate"))
    if result.returncode != 0:
        raise RuntimeError("GitHub could not list the organizations available to this account.")
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
        raise RuntimeError("No organization with a complete Copilot handoff was found for this account.")
    raise RuntimeError("More than one organization has a Copilot handoff. Choose one with --org <name>.")


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _resolve_foundation_ref(product: str, requested: str, *, run: Run) -> str:
    if _SEMVER.match(requested):
        return requested
    floor = _SEMVER.match(requested.removeprefix("^")) if requested.startswith("^") else None
    if floor is None:
        raise RuntimeError(f"Unsupported {product} foundation ref {requested!r}.")
    result = run(("gh", "api", f"repos/Everyone-Needs-A-Copilot/{product}-copilot/tags", "--paginate"))
    if result.returncode != 0:
        raise RuntimeError(f"GitHub could not resolve the {product} foundation release.")
    try:
        tags = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GitHub returned unreadable {product} release tags.") from exc
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
        raise RuntimeError(f"No published {product} foundation release satisfies {requested}.")
    return max(candidates)[1]


def _layer_manifest(org: str, owner: str, products: Sequence[str], handoff: dict[str, Any], *, run: Run) -> dict[str, Any]:
    refs = (handoff.get("foundation") or {}).get("refs") or {}
    layers: list[dict[str, Any]] = []
    for product in products:
        requested = refs.get(product)
        if not isinstance(requested, str) or not requested:
            raise RuntimeError(f"The organization handoff is missing foundation.refs.{product}.")
        exact_ref = _resolve_foundation_ref(product, requested, run=run)
        for layer_id, role, rank, repo, ref, auth in (
            (f"{product}-personal", "personal", 10, f"git@github-personal:{owner}/{product}-copilot-private.git", "main", "personal"),
            (f"{product}-organization", "organization", 30, f"git@github-work:{org}/{product}-copilot-internal.git", "main", "work"),
            (f"{product}-foundation", "foundation", 40, f"https://github.com/Everyone-Needs-A-Copilot/{product}-copilot.git", exact_ref, "anon"),
        ):
            source: dict[str, str] = {"repo": repo, "ref": ref}
            if product == "claude" and role == "foundation":
                source["subpath"] = ".claude"
            layers.append({
                "id": layer_id, "role": role, "rank": rank, "product": product,
                "source": source, "auth": auth, "activation": "always",
                "policy": {"allowed_signers": []},
            })
    return {"version": 1, "org": org, "layers": layers}


def _atomic_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        handle.write(yaml.safe_dump(payload, sort_keys=False))
        temp = Path(handle.name)
    os.replace(temp, path)


def _provision_store(store: dict[str, Any], *, apply: bool, run: Run) -> dict[str, Any]:
    if store.get("status") != "connected":
        return {"result": "deferred"}
    if store.get("type") != "infisical":
        return {"result": "blocked", "detail": "Automated device identity provisioning currently supports Infisical."}
    required = ("workspace_id", "environment", "secret_path")
    if not all(isinstance(store.get(key), str) and store.get(key) for key in required):
        return {"result": "blocked", "detail": "The Admin handoff is missing workspace_id, environment, or secret_path."}
    args = [
        "copilot", "infisical", "--json", "identity", "provision",
        "--project", store["workspace_id"], "--environment", store["environment"],
        "--secret-path", store["secret_path"],
    ]
    if apply:
        args.append("--apply")
    result = run(tuple(args))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"result": "blocked", "detail": "The secret-store provisioner returned an unreadable response."}
    if result.returncode != 0 or payload.get("result") == "blocked":
        return {"result": "blocked", "detail": payload.get("detail", "The secret-store identity could not be provisioned.")}
    return {"result": payload.get("result", "ready"), "type": "infisical", "scope": payload.get("scope")}


def _install_codex_plugin(*, apply: bool, run: Run) -> dict[str, Any]:
    root = Path(str(resolve_key("paths.codex_materialize_root"))).expanduser()
    plugin = root / "plugins" / "codex-copilot"
    marketplace = root / ".agents" / "plugins" / "marketplace.json"
    if not apply:
        ready = plugin.joinpath(".codex-plugin", "plugin.json").is_file() and marketplace.is_file()
        return {"result": "ready" if ready else "changes-required"}
    if not plugin.joinpath(".codex-plugin", "plugin.json").is_file():
        return {"result": "blocked", "detail": "The verified Codex Copilot plugin was not materialized."}
    payload = {
        "name": "enac-materialized",
        "interface": {"displayName": "Copilot Control Tower"},
        "plugins": [{
            "name": "codex-copilot",
            "source": {"source": "local", "path": "./plugins/codex-copilot"},
            "policy": {"installation": "INSTALLED_BY_DEFAULT", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        }],
    }
    marketplace.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=marketplace.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
        temp = Path(handle.name)
    os.replace(temp, marketplace)
    added = run(("codex", "plugin", "marketplace", "add", str(root), "--json"))
    if added.returncode != 0:
        return {"result": "blocked", "detail": "Codex could not register the verified local marketplace."}
    installed = run(("codex", "plugin", "add", "codex-copilot@enac-materialized", "--json"))
    if installed.returncode != 0:
        return {"result": "blocked", "detail": "Codex could not install Codex Copilot from the verified marketplace."}
    return {"result": "ready"}


def _ecosystem_result(
    org: str, products: Sequence[str], apply: bool, result: str,
    stages: list[dict[str, Any]], layers: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report = {"schema_version": SCHEMA_VERSION, "scope": "ecosystem", "mode": "apply" if apply else "plan", "result": result, "org": org, "products": list(products), "stages": stages}
    report["layers"] = [
        {"id": layer["id"], "product": layer["product"], "role": layer["role"], "rank": layer["rank"]}
        for layer in (layers or ())
    ]
    return report


def build_ecosystem_onboard_report(
    *, org: str, products: Sequence[str] = PRODUCTS, apply: bool = False,
    run: Run = _run, manifest_path: Path | str | None = None,
    personal_fn: Callable[..., dict[str, Any]] = build_personal_onboard_report,
    ssh_fn: Callable[..., dict[str, Any]] = ensure_machine_ssh_identity,
    store_fn: Callable[..., dict[str, Any]] = _provision_store,
    codex_fn: Callable[..., dict[str, Any]] = _install_codex_plugin,
    update_fn: Callable[..., tuple[dict[str, Any], int]] = execute_update,
    doctor_fn: Callable[..., dict[str, Any]] = build_doctor_report,
) -> dict[str, Any]:
    """Run the resumable Admin-handoff-to-healthy-machine transaction."""
    normalized = tuple(dict.fromkeys(value.strip().lower() for value in products))
    org = org.strip()
    if not org or not normalized or any(value not in PRODUCTS for value in normalized):
        raise ValueError("An organization and supported products (claude,codex) are required.")
    if org.casefold() == "auto":
        org = _discover_org(normalized, run=run)
    stages: list[dict[str, Any]] = []
    handoff = _load_handoff(org, normalized, run=run)
    stages.append({"stage": "organization-handoff", "result": "ready"})
    personal = personal_fn(components=normalized, apply=apply, run=run)
    stages.append({"stage": "personal-packages", "result": personal["result"], "summary": personal["summary"]})
    if personal["result"] == "blocked":
        return _ecosystem_result(org, normalized, apply, "blocked", stages)
    ssh = ssh_fn(apply=apply, run=run)
    stages.append({"stage": "device-ssh", **ssh})
    if ssh["result"] == "blocked":
        return _ecosystem_result(org, normalized, apply, "blocked", stages)
    manifest = _layer_manifest(org, personal["owner"], normalized, handoff, run=run)
    target = Path(manifest_path).expanduser() if manifest_path else Path.home() / ".copilot" / "copilot.layers.yml"
    stages.append({"stage": "layer-manifest", "result": "ready" if target.exists() else "changes-required", "path": str(target), "layers": len(manifest["layers"])})
    store = handoff.get("store") or {}
    store_report = store_fn(store, apply=apply, run=run)
    stages.append({"stage": "secret-store", **store_report})
    if store_report["result"] == "blocked":
        return _ecosystem_result(org, normalized, apply, "blocked", stages, manifest["layers"])
    if "codex" in normalized:
        codex_plan = codex_fn(apply=False, run=run)
        stages.append({"stage": "codex-plugin", **codex_plan})
    if not apply:
        return _ecosystem_result(org, normalized, False, "changes-required", stages, manifest["layers"])
    _atomic_yaml(target, manifest)
    write_config("layers.manifest", str(target))
    next(stage for stage in stages if stage["stage"] == "layer-manifest")["result"] = "applied"
    update, update_exit = update_fn(dry_run=False)
    stages.append({"stage": "materialize", "result": update.get("result", "blocked"), "blocked": len(update.get("blocked", [])), "held": len(update.get("held_for_approval", []))})
    if update_exit == 0 and "codex" in normalized:
        codex_report = codex_fn(apply=True, run=run)
        next(stage for stage in stages if stage["stage"] == "codex-plugin").update(codex_report)
        if codex_report["result"] == "blocked":
            return _ecosystem_result(org, normalized, True, "blocked", stages, manifest["layers"])
    doctor = doctor_fn()
    stages.append({"stage": "doctor", "result": doctor.get("status", "unknown"), "score": doctor.get("score")})
    result = "ready" if update_exit == 0 and doctor.get("status") == "healthy" else "blocked"
    return _ecosystem_result(org, normalized, True, result, stages, manifest["layers"])


def onboard_cmd(
    scope: str = typer.Option("personal", "--scope", help="Repository scope; currently personal."),
    components: str = typer.Option(",".join(COMPONENTS), "--components", help="Comma-separated ecosystem components."),
    apply: bool = typer.Option(False, "--apply", help="Create confirmed-missing private repositories."),
    output_json: bool = typer.Option(False, "--json", help="Emit the versioned onboarding report."),
    org: str | None = typer.Option(None, "--org", help="Organization slug for the complete ecosystem transaction."),
    products: str = typer.Option(",".join(PRODUCTS), "--products", help="Comma-separated Copilot products."),
) -> None:
    """Discover personal repositories, then optionally create confirmed-missing ones."""
    if org:
        try:
            report = build_ecosystem_onboard_report(org=org, products=products.split(","), apply=apply)
        except (RuntimeError, ValueError) as exc:
            if output_json:
                typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "onboard-unavailable", "message": str(exc)}}))
            else:
                typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['org']}")
        if report["result"] == "blocked":
            raise typer.Exit(1)
        return
    if scope != "personal":
        message = "Only personal onboarding is available from the user CLI."
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "unsupported-scope", "message": message}}))
        raise typer.Exit(2)
    try:
        report = build_personal_onboard_report(components=components.split(","), apply=apply)
    except (RuntimeError, ValueError) as exc:
        if output_json:
            typer.echo(json.dumps({"schema_version": SCHEMA_VERSION, "error": {"code": "onboard-unavailable", "message": str(exc)}}))
        else:
            typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    typer.echo(json.dumps(report) if output_json else f"{report['result']}: {report['owner']}")
    if report["result"] == "blocked":
        raise typer.Exit(1)
