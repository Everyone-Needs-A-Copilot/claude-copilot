"""The shared launcher runtime installs verified CLI packages, never live code."""
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from cc.core.release.engine import build, layout


@pytest.mark.parametrize("fail_install", [False, True])
def test_shared_runtime_installs_signed_cli_packages_together_and_retains_scratch(tmp_path, monkeypatch, fail_install):
    packages = ["cli-copilot", "cli/organization", "cli/department-accounting", "cli/personal"]
    for name in packages:
        path = tmp_path / name
        path.mkdir(parents=True)
        (path / "pyproject.toml").write_text("[project]\nname='fixture'\n")
    scratch = tmp_path / ".cc-shim-scratch"
    scratch.write_text("original temporary shim\n")
    components = [SimpleNamespace(name=name, path=name, kind=layout.KIND_LIVE if name.endswith("personal") else layout.KIND_SIGNED)
                  for name in packages[1:]]
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if "pip" in argv and fail_install:
            raise subprocess.CalledProcessError(1, argv, stderr="dependency install failed")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(build.subprocess, "run", run)
    monkeypatch.setenv("CC_RETAIN_SCRATCH", "1")
    monkeypatch.setenv("PYTHONPATH", "/untrusted/ambient/package")
    if fail_install:
        with pytest.raises(build.ReleaseBuildError, match="dependency install failed"):
            build.build_cc_venv(tmp_path, components)
    else:
        build.build_cc_venv(tmp_path, components)
    assert len(calls) == 2
    assert calls[1][0] == [str(tmp_path / layout.CC_VENV_PYTHON_RELATIVE), "-m", "pip", "install", "--quiet",
                           *[str(tmp_path / name) for name in packages[:3]]]
    assert all("PYTHONPATH" not in kwargs["env"] for _, kwargs in calls)
    assert scratch.read_text() == "original temporary shim\n"
