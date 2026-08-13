"""Shared fixtures for the ecosystem conformance harness's test face.

Implements `HARNESS-DESIGN.md` §5 ("Fixture and isolation strategy")'s "two-
world rule": every conformance test runs in exactly one of:

  World A -- Synthetic (`FleetFactory`, below). A complete fake ecosystem
  built entirely under `tmp_path`: a temp `$HOME`, a generated
  `copilot.layers.yml`, and real-git fake tier repos (real commits, real
  tags, including real ORPHAN tags for the RC-3 ancestry test — ancestry is
  a genuine git property and a mocked repo cannot fail the way a real one
  does). Nothing outside `tmp_path` is read for state or written at all.

  World B -- Machine truth. Reads the real manifest / real tier repos /
  real project repos, strictly read-only, enforced by the
  `_conformance_machine_readonly_tripwire` autouse fixture below (built on
  `cc.core.conformance.fsguard.MachineReadOnlyGuard`) rather than by
  discipline. Mark these tests `@pytest.mark.machine` so
  `pytest -m "not machine"` gives a fully hermetic run.

This file inherits `tests/conftest.py`'s own `_isolate_machine_config`
autouse fixture via ordinary pytest conftest nesting (NOT modified here —
WP-1 does not touch the shared conftest, per the design's collision-control
table). The tripwire fixture below is layered ON TOP of it, scoped to this
suite specifically.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import pytest
import yaml
from cc.core.conformance.fsguard import MachineReadOnlyGuard

# ---------------------------------------------------------------------------
# pytest wiring
# ---------------------------------------------------------------------------


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        'machine: exercises real machine state, strictly read-only, guarded '
        'by fsguard.MachineReadOnlyGuard. `pytest -m "not machine"` gives a '
        "hermetic run on any machine, including one with no ecosystem "
        "installed (HARNESS-DESIGN.md section 6.5).",
    )


@pytest.fixture(autouse=True)
def _conformance_machine_readonly_tripwire():
    """Autouse for every test in `tests/conformance/`: fingerprints the
    fixed core guarded set (real machine config/secrets, the real global
    memory root's tracked targets, and all three real `copilot.layers.yml`
    paths) before and after the test, and fails loudly, naming the
    offending path(s), if anything changed.

    This is layered ON TOP OF (never a replacement for)
    `tests/conftest.py::_isolate_machine_config`, which the whole `cc` test
    suite already inherits. World-A (synthetic fleet) tests never touch
    these real paths at all, so this is a true no-op assertion for them;
    World-B (machine-truth) tests are exactly what it exists to guard, and
    it fires REGARDLESS of whether the test itself passed or failed.
    """

    with MachineReadOnlyGuard(include_core_paths=True):
        yield


@pytest.fixture
def machine_readonly_guard() -> Callable[..., MachineReadOnlyGuard]:
    """Factory for a World-B test that reads dynamic real paths beyond the
    fixed core set (a specific tier repo, a specific project's dimension
    paths): `with machine_readonly_guard(extra_paths=[...]):`."""

    def _factory(
        extra_paths: Iterable[Path] = (), *, include_core_paths: bool = True
    ) -> MachineReadOnlyGuard:
        return MachineReadOnlyGuard(
            extra_paths=extra_paths, include_core_paths=include_core_paths
        )

    return _factory


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def _run_git(
    args: Iterable[str], *, cwd: Path, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=check
    )


def init_git_repo(path: Path) -> None:
    """Real `git init` with a deterministic local identity (never relies on
    global git config, which a sandboxed test runner may not have)."""

    path.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-q", "-b", "main"], cwd=path)
    _run_git(["config", "user.email", "fleet@conformance.invalid"], cwd=path)
    _run_git(["config", "user.name", "Conformance Fleet"], cwd=path)


def git_commit_all(path: Path, message: str) -> str:
    """Stage everything and commit (allow-empty, since a tier may be
    pinned before it has any dimension content). Returns the new HEAD sha."""

    _run_git(["add", "-A"], cwd=path)
    _run_git(["commit", "-q", "--allow-empty", "-m", message], cwd=path)
    return _run_git(["rev-parse", "HEAD"], cwd=path).stdout.strip()


def git_orphan_tag(path: Path, tag: str, *, message: str = "orphan snapshot") -> str:
    """Create a commit with NO PARENT (unreachable from any branch) and tag
    it — reproduces RC-3's exact defect (`HARNESS-DESIGN.md` §5.2:
    "`fleet.pin(..., orphan=True)` reproduces the orphan snapshot with `git
    commit-tree` against no parent"). Returns the orphan commit sha."""

    tree = _run_git(["write-tree"], cwd=path).stdout.strip()
    commit = subprocess.run(
        ["git", "commit-tree", tree, "-m", message],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    _run_git(["-c", "tag.gpgSign=false", "tag", tag, commit], cwd=path)
    return commit


def git_clone_local(source: Path, dest: Path) -> Path:
    """`git clone --local --no-hardlinks` — the ONLY sanctioned way any
    conformance test (Layer 5's round-trip, in particular) gets a mutable,
    disposable copy of a git repository. `source` must always itself be a
    `tmp_path` fixture repo — never a real product repo
    (`HARNESS-DESIGN.md` §5.3: "No real repo is ever a test's write target:
    Layer 5's round-trip clones its subject with `git clone --local
    --no-hardlinks` into `tmp_path`")."""

    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_git(
        ["clone", "--quiet", "--local", "--no-hardlinks", str(source), str(dest)],
        cwd=dest.parent,
    )
    return dest


# ---------------------------------------------------------------------------
# FleetFactory — the World-A synthetic fleet builder
# ---------------------------------------------------------------------------

_ROLE_RANK_DEFAULT: Mapping[str, int] = {
    "foundation": 40,
    "organization": 30,
    "department": 20,
    "personal": 10,
}


def _tier_dir_name(product: str, role: str, unit: str | None) -> str:
    if role == "foundation":
        return f"{product}-copilot"
    if role == "organization":
        return f"{product}-copilot-internal"
    if role == "department":
        return f"{product}-copilot-{unit or 'engineering'}"
    if role == "personal":
        return f"{product}-copilot-private"
    raise ValueError(
        f"unknown tier role {role!r}; must be one of "
        f"{sorted(_ROLE_RANK_DEFAULT)}"
    )


@dataclass
class TierBuilder:
    """One tier-variant repo: real git, real commits, real tags. Fluent —
    every mutator returns `self`."""

    product: str
    role: str
    rank: int
    path: Path
    unit: str | None = None
    pinned_ref: str | None = None

    @property
    def layer_id(self) -> str:
        return f"{self.product}-{self.role}"

    def contributes(self, dimension: str, items: Mapping[str, str]) -> "TierBuilder":
        """Write one file per item under `<tier>/<dimension>/<item>.md` —
        the exact shape `cc.core.ecosystem.discovery.discover_contributions`
        scans (a subdirectory per dimension, one file — or directory — per
        item, hashed by content). An empty string is a legal, deliberate
        value (`HARNESS-DESIGN.md`'s own example: `contributes("agents",
        {"cw": ""})` — "the empty-shadow case")."""

        dim_dir = self.path / dimension
        dim_dir.mkdir(parents=True, exist_ok=True)
        for name, content in items.items():
            (dim_dir / f"{name}.md").write_text(content, encoding="utf-8")
        git_commit_all(
            self.path, f"contribute {dimension}: {', '.join(sorted(items))}"
        )
        return self

    def write(
        self, relative: str, content: str | bytes, *, executable: bool = False
    ) -> "TierBuilder":
        """Raw file write for content `contributes()`'s dimension-folder
        convention doesn't cover (e.g. `knowledge-manifest.json`, a
        `.claude/extensions/<agent>.extension.md` scaffold for the
        tier.shadow.* substance checks)."""

        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        if executable:
            target.chmod(target.stat().st_mode | 0o111)
        git_commit_all(self.path, f"write {relative}")
        return self

    def pin(self, ref: str, *, orphan: bool = False) -> "TierBuilder":
        """Tag the tier at `ref`. `orphan=True` reproduces RC-3 exactly
        (a parentless commit, tagged, unreachable from `main`); otherwise
        tags the current `HEAD` (a normal, ancestor-of-main release)."""

        if orphan:
            git_orphan_tag(self.path, ref)
        else:
            _run_git(["-c", "tag.gpgSign=false", "tag", ref], cwd=self.path)
        self.pinned_ref = ref
        return self

    def manifest_layer(self) -> dict[str, Any]:
        source: dict[str, Any] = {"repo": f"file://{self.path}", "path": str(self.path)}
        if self.pinned_ref is not None:
            source["ref"] = self.pinned_ref
        layer: dict[str, Any] = {
            "id": self.layer_id,
            "role": self.role,
            "rank": self.rank,
            "product": self.product,
            "source": source,
            "auth": "anon",
            "activation": "always",
        }
        if self.unit is not None:
            layer["unit"] = self.unit
        return layer


@dataclass
class ProductBuilder:
    name: str
    root: Path
    _tiers: dict[str, TierBuilder] = field(default_factory=dict)

    def tier(
        self, role: str, rank: int | None = None, *, unit: str | None = None
    ) -> TierBuilder:
        if role in self._tiers:
            return self._tiers[role]
        if role == "department":
            unit = unit or "engineering"
        effective_rank = rank if rank is not None else _ROLE_RANK_DEFAULT[role]
        path = self.root / _tier_dir_name(self.name, role, unit)
        init_git_repo(path)
        (path / ".gitkeep").write_text("", encoding="utf-8")
        git_commit_all(path, "initial commit")
        builder = TierBuilder(
            product=self.name, role=role, rank=effective_rank, path=path, unit=unit
        )
        self._tiers[role] = builder
        return builder

    def tiers(self) -> tuple[TierBuilder, ...]:
        return tuple(self._tiers.values())


@dataclass
class ProjectBuilder:
    """One project (a scratch install target or a fixture project like a
    named degradation). Not necessarily a git repo — call `git_init()`
    explicitly when a check needs one (e.g. D13 tier-participation
    scanning, or anything Layer 5 clones)."""

    name: str
    path: Path

    def install(
        self, spec: Mapping[str, str | bytes] | Callable[[Path], None]
    ) -> "ProjectBuilder":
        if callable(spec):
            spec(self.path)
        else:
            for relative, content in spec.items():
                self.write(relative, content)
        return self

    def write(
        self, relative: str, content: str | bytes, *, executable: bool = False
    ) -> "ProjectBuilder":
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")
        if executable:
            target.chmod(target.stat().st_mode | 0o111)
        return self

    def remove(self, relative: str) -> "ProjectBuilder":
        target = self.path / relative
        if target.exists():
            target.unlink()
        return self

    def git_init(self) -> "ProjectBuilder":
        init_git_repo(self.path)
        git_commit_all(self.path, "initial commit")
        return self


@dataclass
class FleetHandle:
    """The built fleet: every path a test needs, plus `env` — the
    environment variables that make in-process AND subprocess `cc`
    invocations resolve against this synthetic fleet instead of the real
    machine (`HOME`, `CC_MACHINE_ROOT`, `XDG_CONFIG_HOME`). Apply them with
    the `apply_fleet_env` fixture for an in-process test, or merge them
    into a subprocess's `env=` for a CLI-invocation test."""

    tmp_path: Path
    home: Path
    manifest_path: Path
    tiers: Mapping[tuple[str, str], Path]
    projects: Mapping[str, Path]
    env: Mapping[str, str]


class FleetFactory:
    """Fluent builder for a complete synthetic ecosystem under `tmp_path`
    (`HARNESS-DESIGN.md` §5.2)::

        fleet = FleetFactory(tmp_path)
        fleet.product("claude").tier("foundation", rank=40).contributes(
            "agents", {"cw": "real org content"}
        )
        fleet.product("claude").tier("personal", rank=10).contributes(
            "agents", {"cw": ""}
        )  # the empty-shadow case
        fleet.pin("claude", "foundation", ref="v1.0.0", orphan=True)  # RC-3
        fleet.project("degraded-no-hook").install(reference).remove(
            ".claude/hooks/copilot-hook.sh"
        )
        handle = fleet.build()

    Arity-independent by construction: any number of products, and any
    subset of the four tier roles per product — nothing here hardcodes
    "four tiers" or "four products" (matching the resolver's own
    arity-independence guarantee, `cc.core.ecosystem.resolver`'s module
    docstring).
    """

    def __init__(self, tmp_path: Path) -> None:
        self._tmp_path = tmp_path
        self._home = tmp_path / "home"
        self._tiers_root = tmp_path / "tiers"
        self._projects_root = tmp_path / "projects"
        self._products: dict[str, ProductBuilder] = {}
        self._projects: dict[str, ProjectBuilder] = {}

    def product(self, name: str) -> ProductBuilder:
        if name not in self._products:
            self._tiers_root.mkdir(parents=True, exist_ok=True)
            self._products[name] = ProductBuilder(name=name, root=self._tiers_root)
        return self._products[name]

    def pin(
        self, product: str, role: str, *, ref: str, orphan: bool = False
    ) -> "FleetFactory":
        self.product(product).tier(role).pin(ref, orphan=orphan)
        return self

    def project(self, name: str) -> ProjectBuilder:
        if name not in self._projects:
            path = self._projects_root / name
            path.mkdir(parents=True, exist_ok=True)
            self._projects[name] = ProjectBuilder(name=name, path=path)
        return self._projects[name]

    def build(self) -> FleetHandle:
        home = self._home
        (home / ".claude" / "cc").mkdir(parents=True, exist_ok=True)
        (home / ".config" / "copilot").mkdir(parents=True, exist_ok=True)

        manifest_path = home / ".config" / "copilot" / "copilot.layers.yml"
        layers: list[dict[str, Any]] = []
        for product in self._products.values():
            for tier in sorted(product.tiers(), key=lambda entry: entry.rank):
                layers.append(tier.manifest_layer())
        manifest_path.write_text(
            yaml.safe_dump({"version": 1, "layers": layers}, sort_keys=False),
            encoding="utf-8",
        )

        machine_config = {
            "layers": {"manifest": str(manifest_path)},
            "paths": {"mirrors_root": str(home / ".copilot" / "mirrors")},
        }
        (home / ".claude" / "cc" / "config.json").write_text(
            json.dumps(machine_config, indent=2, sort_keys=True), encoding="utf-8"
        )

        env = {
            "HOME": str(home),
            "CC_MACHINE_ROOT": str(home / ".claude" / "cc"),
            "XDG_CONFIG_HOME": str(home / ".config"),
        }

        tiers = {
            (product.name, tier.role): tier.path
            for product in self._products.values()
            for tier in product.tiers()
        }
        projects = {name: builder.path for name, builder in self._projects.items()}

        return FleetHandle(
            tmp_path=self._tmp_path,
            home=home,
            manifest_path=manifest_path,
            tiers=tiers,
            projects=projects,
            env=env,
        )


# ---------------------------------------------------------------------------
# pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fleet_factory(tmp_path: Path) -> FleetFactory:
    """Ergonomic fixture-injection form of `FleetFactory(tmp_path)`."""

    return FleetFactory(tmp_path)


@pytest.fixture
def apply_fleet_env(monkeypatch: pytest.MonkeyPatch) -> Callable[[FleetHandle], FleetHandle]:
    """`apply_fleet_env(handle)` — `monkeypatch.setenv` every entry in
    `handle.env`, so subsequent IN-PROCESS `cc` calls (that resolve config
    via `resolve_key`/`Path.home()` rather than explicit DI) resolve
    against the synthetic fleet for the rest of this test."""

    def _apply(handle: FleetHandle) -> FleetHandle:
        for key, value in handle.env.items():
            monkeypatch.setenv(key, value)
        return handle

    return _apply
