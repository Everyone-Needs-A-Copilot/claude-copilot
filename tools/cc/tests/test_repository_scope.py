from __future__ import annotations

import subprocess
from pathlib import Path

from cc.core.ecosystem.repository_scope import (
    managed_ecosystem_repositories,
    repository_identity,
)


def _git(path: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )


def _checkout(root: Path, name: str, repository: str) -> Path:
    path = root / name
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "remote", "add", "origin", f"git@github.com:{repository}.git")
    return path


def _layer(
    *, layer_id: str, product: str, role: str, rank: int, path: Path, repo: str
) -> dict:
    return {
        "id": layer_id,
        "product": product,
        "role": role,
        "rank": rank,
        "source": {"path": str(path), "repo": repo},
        "auth": {},
        "activation": "always",
    }


def test_repository_identity_normalizes_supported_github_transports() -> None:
    assert repository_identity("git@github.com:Owner/Repo.git") == "owner/repo"
    assert repository_identity("https://github.com/OWNER/Repo.git") == "owner/repo"
    assert repository_identity("owner/repo") == "owner/repo"
    assert repository_identity("https://example.com/owner/repo") is None
    assert repository_identity("repo-only") is None


def test_all_four_products_and_levels_require_manifest_plus_origin_proof(
    tmp_path: Path,
) -> None:
    roles = ("personal", "department", "organization", "foundation")
    layers: list[dict] = []
    expected: set[str] = set()
    for product in ("knowledge", "cli", "claude", "codex"):
        for index, role in enumerate(roles, start=1):
            name = f"{product}-{role}"
            repository = f"everyone-needs-a-copilot/{name}"
            checkout = _checkout(tmp_path, name, repository)
            expected.add(str(checkout.resolve()))
            layers.append(
                _layer(
                    layer_id=name,
                    product=product,
                    role=role,
                    rank=index * 10,
                    path=checkout,
                    repo=repository,
                )
            )

    scopes = managed_ecosystem_repositories(manifest_source=layers)

    assert set(scopes) == expected
    assert {scope["product"] for scope in scopes.values()} == {
        "knowledge",
        "cli",
        "claude",
        "codex",
    }
    assert {scope["role"] for scope in scopes.values()} == set(roles)


def test_names_symlinks_and_wrong_origins_never_remove_a_product_project(
    tmp_path: Path,
) -> None:
    wrong_origin = _checkout(tmp_path, "claude-copilot", "owner/not-claude")
    target = _checkout(tmp_path, "codex-target", "owner/codex")
    linked = tmp_path / "codex-copilot"
    linked.symlink_to(target, target_is_directory=True)
    ordinary = _checkout(tmp_path, "method-copilot", "owner/method-copilot")
    layers = [
        _layer(
            layer_id="claude-foundation",
            product="claude",
            role="foundation",
            rank=10,
            path=wrong_origin,
            repo="owner/claude",
        ),
        _layer(
            layer_id="codex-foundation",
            product="codex",
            role="foundation",
            rank=10,
            path=linked,
            repo="owner/codex",
        ),
    ]

    scopes = managed_ecosystem_repositories(manifest_source=layers)

    assert scopes == {}
    assert ordinary.name.endswith("-copilot")
