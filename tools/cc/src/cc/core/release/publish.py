"""`cc release publish`: build, flip, links, Codex marketplace, doctor, history (ADR-001 decision 8).

Fails closed. Any failure after the pointer flipped restores the previous
release, its link plan and the Codex config, then raises `PublishError` with the
exact rollback command so the owner can see the state that was restored.
"""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from .codex import marketplace as codex_marketplace
from .codex import step as codex_step
from .codex import config as codex_config
from .engine import build, doctor, layout, pointer, schema
from .links import apply_plan, build_plan, plan_from_json, write_plan

CONTROL_TOWER_APP = Path("/Applications/Copilot Control Tower.app")
_AGENTS_COMMENT = re.compile(r"\A\s*<!--.*?-->\s*", re.DOTALL)


class PublishError(RuntimeError):
    """Publish failed; `restored` says whether the previous state is back in place."""

    def __init__(self, message: str, *, step: str, restored: bool, rollback_hint: str) -> None:
        super().__init__(message)
        self.step = step
        self.restored = restored
        self.rollback_hint = rollback_hint


@dataclass
class PublishReport:
    release_id: str
    previous: str | None
    flipped: bool = False
    links: dict = field(default_factory=dict)
    codex: dict = field(default_factory=dict)
    checks: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"release": self.release_id, "previous": self.previous, "flipped": self.flipped,
                "links": self.links, "codex": self.codex, "checks": self.checks}


def control_tower_pin(app: Path | str = CONTROL_TOWER_APP, metadata: Path | str | None = None) -> dict:
    """The control-tower record pin: version from the installed app, commit from its release metadata."""
    app = Path(app)
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    except (OSError, plistlib.InvalidFileException) as exc:
        raise build.ReleaseBuildError(f"control-tower app not readable at {app}: {exc}") from exc
    version = str(info.get("CFBundleShortVersionString", ""))
    pin = {"version": version, "ref": f"refs/tags/v{version}", "source": str(app), "commit": ""}
    if metadata:
        meta = json.loads(Path(metadata).read_text(encoding="utf-8"))
        if meta.get("version") != version:
            raise build.ReleaseBuildError(
                f"control-tower metadata version {meta.get('version')} != installed app {version}")
        pin["ref"] = meta.get("source_ref", pin["ref"])
        pin["commit"] = meta.get("source_commit", "")
    return pin


def write_release_files(target: Path, *, command_skill_names: Sequence[str] = (),
                        project_roots: Sequence[Path | str] = (), home: Path | str | None = None,
                        framework_repos: Sequence[Path | str] = ()) -> None:
    """Generated per-release artifacts: the Codex AGENTS block and the link plan."""
    template = target / layout.COMPONENT_CODEX / "templates" / "codex-AGENTS.framework.md"
    if template.is_file():
        text = _AGENTS_COMMENT.sub("", template.read_text(encoding="utf-8"), count=1)
        (target / layout.CODEX_AGENTS_BLOCK_NAME).write_text(text.strip("\n") + "\n", encoding="utf-8")
    plan = build_plan(target, home, command_skill_names=command_skill_names, project_roots=project_roots,
                      framework_repos=framework_repos)
    write_plan(plan, target)


def write_source_markers(target: Path, components: Sequence[schema.Component]) -> None:
    """Bind the extracted framework to its verified commit so `tc provenance` runs in snapshot mode."""
    item = next(c for c in components if c.name == layout.COMPONENT_CLAUDE)
    tree = subprocess.run(["git", "-C", item.source, "rev-parse", f"{item.commit}^{{tree}}"],
                          capture_output=True, text=True, check=False)
    if tree.returncode != 0 or not tree.stdout.strip():
        raise build.ReleaseBuildError(f"cannot resolve the tree of {item.commit} in {item.source}")
    root = target / layout.COMPONENT_CLAUDE
    (root / ".source-commit").write_text(item.commit + "\n", encoding="utf-8")
    (root / ".source-tree").write_text(tree.stdout.strip() + "\n", encoding="utf-8")


def make_post_build(home: Path | str | None = None, *, strict_frozen: bool = True,
                    retrust: Sequence[str] | bool = (), venv: bool = True,
                    command_skill_names: Sequence[str] = (),
                    project_roots: Sequence[Path | str] = ()) -> build.PostBuild:
    """Compose the build post-steps: cc venv, Codex marketplace (frozen-core check), generated files."""
    marketplace_step = codex_marketplace.make_post_build(home, retrust=retrust, strict_frozen=strict_frozen)

    def hook(target: Path, components: Sequence[schema.Component]) -> None:
        if venv:
            write_source_markers(target, components)
            build.build_cc_venv(target, components)
        marketplace_step(target, components)
        write_release_files(target, command_skill_names=command_skill_names, project_roots=project_roots,
                            home=home, framework_repos=[c.source for c in components if c.tier == "framework"])
    return hook


def control_tower_check(app: Path | str = CONTROL_TOWER_APP) -> Callable[[Path], list[doctor.Check]]:
    """Doctor hook: installed Control Tower version equals the release record (warn-as-fail on drift)."""
    def check(root: Path) -> list[doctor.Check]:
        try:
            recorded = schema.load(root).component(layout.COMPONENT_CONTROL_TOWER).version
        except (schema.ReleaseSchemaError, KeyError) as exc:
            return [doctor.Check("control-tower", False, str(exc))]
        try:
            installed = control_tower_pin(app)["version"]
        except build.ReleaseBuildError as exc:
            return [doctor.Check("control-tower", False, str(exc))]
        return [doctor.Check("control-tower", installed == recorded,
                             f"installed {installed}, release records {recorded}")]
    return check


def links_check(home: Path | str | None = None) -> Callable[[Path], list[doctor.Check]]:
    """Doctor hook: the links receipt belongs to the current release."""
    def check(root: Path) -> list[doctor.Check]:
        try:
            receipt = json.loads(layout.links_receipt_path(home).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return [doctor.Check("links", False, f"no links receipt: {exc}")]
        ok = receipt.get("release") == root.name
        overrides = receipt.get("personal_overrides", [])
        listed = ", ".join(sorted(f"{o['kind']}:{o['name']}" for o in overrides)) or "none"
        return [doctor.Check("links", ok, f"receipt {receipt.get('release')}, current {root.name}; "
                                          f"{len(receipt.get('links', []))} links; "
                                          f"{len(receipt.get('kept', []))} kept owner/tool items"),
                doctor.Check("personal-overrides", True, f"{len(overrides)} personal override(s): {listed}")]
    return check


def run_doctor(home: Path | str | None = None, codex_home: Path | str | None = None,
               *, control_tower_app: Path | str = CONTROL_TOWER_APP) -> list[doctor.Check]:
    """The complete `cc doctor --release` check set."""
    extra = [codex_step.doctor_checks(codex_home, home), links_check(home),
             control_tower_check(control_tower_app)]
    return doctor.run(home, extra=extra)


def _restore(home, codex_home, previous: str | None, flipped: bool, config_changed: bool) -> bool:
    ok = True
    try:
        if config_changed:
            codex_config.rollback(home, force=True)
        if flipped and previous:
            pointer.rollback(home, to=previous, reason="publish failed; automatic restore")
            plan_path = layout.release_dir(previous, home) / layout.LINK_PLAN_NAME
            if plan_path.is_file():
                apply_plan(plan_from_json(json.loads(plan_path.read_text(encoding="utf-8"))), home)
        elif flipped:
            layout.current_path(home).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - restore failure is reported, not raised over the original
        ok = False
    return ok


def publish(sources: Sequence[build.ComponentSource], home: Path | str | None = None,
            codex_home: Path | str | None = None, *, strict_frozen: bool = True,
            retrust: Sequence[str] | bool = (), venv: bool = True,
            command_skill_names: Sequence[str] = (), project_roots: Sequence[Path | str] = (),
            verifier: build.Verifier = build.default_verifier,
            extractor: build.Extractor = build.default_extractor,
            codex_runner: codex_step.Runner = codex_step.default_runner, codex_bin: str = "codex",
            control_tower_app: Path | str = CONTROL_TOWER_APP) -> PublishReport:
    previous = pointer.current_release_id(home)
    hint = "cc release rollback" + (f" --to {previous}" if previous else "")
    try:
        manifest = build.build_release(
            sources, home, verifier=verifier, extractor=extractor,
            post_build=make_post_build(home, strict_frozen=strict_frozen, retrust=retrust, venv=venv,
                                       command_skill_names=command_skill_names, project_roots=project_roots))
    except Exception as exc:  # nothing was flipped; the partial directory is already removed
        raise PublishError(f"build failed: {exc}", step="build", restored=True, rollback_hint=hint) from exc
    report = PublishReport(manifest.release_id, previous)
    step = "flip"
    config_changed = False
    try:
        pointer.flip(manifest.release_id, home, reason="publish")
        report.flipped = True
        step = "links"
        plan = plan_from_json(json.loads(
            (layout.release_dir(manifest.release_id, home) / layout.LINK_PLAN_NAME).read_text(encoding="utf-8")))
        applied = apply_plan(plan, home, adopt=True)
        report.links = {"created": len(applied.created), "updated": len(applied.updated),
                        "removed": len(applied.removed), "skipped": len(applied.skipped),
                        "adopted": applied.adopted, "customized": applied.customized,
                        "personal_overrides": applied.personal_overrides, "stale_copies": applied.stale_copies,
                        "kept": applied.kept,
                        "errors": applied.errors, "claude_md": applied.claude_md, "agents_md": applied.agents_md}
        if not applied.ok:
            raise RuntimeError("; ".join(applied.errors))
        step = "codex"
        result = codex_step.run(home, codex_home, codex_bin=codex_bin, runner=codex_runner)
        config_changed = result.config.changed
        report.codex = {"refreshed_with": result.refreshed_with, "plugins": result.plugins,
                        "config_changed": result.config.changed}
        step = "doctor"
        checks = run_doctor(home, codex_home, control_tower_app=control_tower_app)
        report.checks = [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]
        failed = [c for c in checks if not c.ok]
        if failed:
            raise RuntimeError("doctor failed: " + "; ".join(f"{c.name}: {c.detail}" for c in failed))
    except Exception as exc:
        restored = _restore(home, codex_home, previous, report.flipped, config_changed)
        raise PublishError(f"{step} failed: {exc}", step=step, restored=restored,
                           rollback_hint=hint) from exc
    return report
