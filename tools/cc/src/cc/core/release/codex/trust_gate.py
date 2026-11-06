"""Pre-flip Codex trust gate (PRD-16 task 200).

Codex trusts a plugin's hooks by a hash over the whole plugin directory. A release must
therefore leave `plugins/codex-copilot` byte-identical (the frozen core) or every approval
resets. Before the pointer flips this gate asks Codex itself (`hooks/list` over
`codex app-server`) what content hash the live plugin has and what the candidate release's
plugin would have, and refuses the flip when they differ. Stale trust entries on the live
machine are an owner action and only produce warnings. The gate never writes trust entries:
the candidate is installed into a throwaway CODEX_HOME.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

from cc.core.release.engine import layout

from . import marketplace

PLUGIN = "codex-copilot"
PLUGIN_ID = f"{PLUGIN}@{marketplace.MARKETPLACE_NAME}"

HooksLister = Callable[[str, Path, Path], list]
Runner = Callable[[Sequence[str], dict], "subprocess.CompletedProcess[str]"]


class TrustGateError(RuntimeError):
    """The flip would change Codex plugin trust, or Codex could not be asked."""


@dataclass
class GateResult:
    warnings: list[str] = field(default_factory=list)
    live_hash: str | None = None
    candidate_hash: str | None = None

    def to_json(self) -> dict:
        return {"warnings": self.warnings, "live_content_hash": self.live_hash,
                "candidate_content_hash": self.candidate_hash}


def app_server_hooks(codex_bin: str, codex_home: Path, cwd: Path, *, wait: float = 3.0,
                     timeout: float = 30.0) -> list:
    """The `hooks/list` hooks for `cwd` as reported by a short-lived `codex app-server`."""
    env = {**os.environ, "CODEX_HOME": str(codex_home)}
    try:
        proc = subprocess.Popen([codex_bin, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=env, text=True, cwd=str(cwd))
    except OSError as exc:
        raise TrustGateError(f"cannot start `{codex_bin} app-server`: {exc}") from exc

    def send(message: dict) -> None:
        proc.stdin.write(json.dumps(message) + "\n")
        proc.stdin.flush()

    def read(request_id: int) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("id") == request_id:
                return message
        raise TrustGateError("codex app-server did not answer hooks/list")

    try:
        send({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "cc-release", "version": "1"}}})
        read(1)
        send({"method": "initialized"})
        time.sleep(wait)
        send({"id": 2, "method": "hooks/list", "params": {"cwds": [str(cwd)]}})
        reply = read(2)
        if "error" in reply:
            raise TrustGateError(f"codex hooks/list failed: {reply['error']}")
        data = reply["result"]["data"]
        return list(data[0]["hooks"]) if data else []
    except (BrokenPipeError, KeyError, IndexError, TypeError) as exc:
        raise TrustGateError(f"codex hooks/list returned an unreadable answer: {exc!r}") from exc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _plugin_hooks(hooks: list) -> list:
    return [h for h in hooks if h.get("pluginId") == PLUGIN_ID]


def content_hashes(hooks: list) -> dict[str, str]:
    """Hook key -> Codex content hash.

    `currentHash` is `<per-hook sha>/<plugin content sha>`; Codex may report a different
    content value per hook, so hashes are compared hook by hook, never as one shared value.
    """
    return {str(h.get("key", "")): str(h.get("currentHash", "")).rpartition("/")[2] for h in _plugin_hooks(hooks)}


def _short(hash_value: str) -> str:
    return hash_value.removeprefix("sha256:")[:12]


def _hook_name(key: str) -> str:
    """`codex-copilot@mkt:hooks/hooks.json:pre_tool_use:0:0` -> `pre_tool_use:0:0`."""
    return key.partition(":hooks/hooks.json:")[2] or key


def changed_hooks(live: dict[str, str], candidate: dict[str, str]) -> list[str]:
    """Hooks whose content hash would change or that the candidate drops."""
    return sorted(_hook_name(k) for k, v in live.items() if candidate.get(k) != v)


def assert_frozen_core(candidate_marketplace: Path, current_receipt: dict | None) -> None:
    """The candidate plugin directory must be byte-identical to the one the current release froze."""
    if not current_receipt:
        return
    frozen = next((p["digest"] for p in current_receipt["plugins"] if p["name"] == PLUGIN), None)
    if frozen is None:
        return
    actual = marketplace.tree_digest(candidate_marketplace / "plugins" / PLUGIN)
    if actual != frozen:
        raise TrustGateError(
            f"{PLUGIN} plugin directory is not byte-identical to the frozen core "
            f"(release digest {actual[:12]}, frozen {frozen[:12]}); Codex trust would reset")


def _candidate_hooks(candidate_marketplace: Path, codex_bin: str, runner: Runner, lister: HooksLister) -> list:
    sandbox = Path(tempfile.mkdtemp(prefix="cc-trust-gate-"))
    try:
        (sandbox / "config.toml").write_text(
            f'[marketplaces.{marketplace.MARKETPLACE_NAME}]\nsource_type = "local"\n'
            f'source = "{candidate_marketplace}"\n\n[plugins."{PLUGIN_ID}"]\nenabled = true\n', encoding="utf-8")
        env = {**os.environ, "CODEX_HOME": str(sandbox)}
        added = runner([codex_bin, "plugin", "add", PLUGIN_ID], env)
        if added.returncode != 0:
            raise TrustGateError(f"candidate plugin could not be installed for hashing: "
                                 f"{(added.stderr or added.stdout).strip()}")
        for _ in range(3):  # plugin loading is asynchronous after app-server start
            hooks = lister(codex_bin, sandbox, sandbox)
            if _plugin_hooks(hooks):
                return hooks
        return []
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def check(release_directory: Path, current_release: Path | None, codex_home: Path, *,
          codex_bin: str = "codex", runner: Runner, lister: HooksLister = app_server_hooks,
          strict: bool = True) -> GateResult:
    """Raise `TrustGateError` unless flipping to `release_directory` leaves Codex plugin trust intact."""
    candidate = release_directory / layout.MARKETPLACE_DIRNAME
    result = GateResult()
    receipt = None
    if current_release is not None:
        try:
            receipt = marketplace.load_receipt(current_release)
        except marketplace.MarketplaceError:
            receipt = None
    if strict:
        assert_frozen_core(candidate, receipt)
    live = _plugin_hooks(lister(codex_bin, codex_home, Path(codex_home)))
    live_hashes = content_hashes(live)
    stale = sorted((h for h in live if h.get("trustStatus") not in ("trusted", "managed")),
                   key=lambda h: str(h.get("key")))
    if stale:
        detail = ", ".join(f"{_hook_name(str(h.get('key')))} {h.get('trustStatus')}" for h in stale)
        trusted = len(live) - len(stale)
        result.warnings.append(
            f"{len(stale)} of {len(live)} {PLUGIN} hook trust entries are not trusted in Codex already "
            f"({trusted} trusted): {detail}; owner re-approval in /hooks is needed (the release never writes trust)")
    candidate_hashes = content_hashes(_candidate_hooks(candidate, codex_bin, runner, lister))
    if not candidate_hashes:
        raise TrustGateError("Codex reported no hooks for the candidate plugin; cannot verify its content hash")
    result.candidate_hash = _summary(candidate_hashes)
    if not live_hashes:
        result.warnings.append("no live Codex hooks for the plugin; no trust baseline to compare against")
        return result
    result.live_hash = _summary(live_hashes)
    changed = changed_hooks(live_hashes, candidate_hashes)
    if changed and strict:
        raise TrustGateError(
            f"{PLUGIN} content hash would change for {', '.join(changed)} "
            f"({result.live_hash} -> {result.candidate_hash}); "
            "Codex trust would reset. No changes made. Keep the plugin directory byte-identical "
            "or pass --no-strict-frozen with a declared re-trust")
    if changed:
        result.warnings.append(f"content hash changes for {', '.join(changed)}; Codex trust resets (non-strict)")
    return result


def _summary(hashes: dict[str, str]) -> str:
    return ",".join(sorted({_short(v) for v in hashes.values()}))
