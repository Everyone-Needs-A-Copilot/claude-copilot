import subprocess
from pathlib import Path

import pytest


def test_installer_bootstraps_pip_for_existing_uv_virtual_environment():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert 'if ! "$VENV_DIR/bin/python" -m pip --version' in source
    assert '"$VENV_DIR/bin/python" -m ensurepip --upgrade' in source
    assert source.index("-m ensurepip --upgrade") < source.index(
        '"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip'
    )


def test_installer_supports_transactional_shim_staging_without_profile_edits():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert "--shim-path" in source
    assert "--no-profile-update" in source
    assert 'SHIM_DIR="$(dirname "$SHIM")"' in source
    assert 'if [ "$UPDATE_PROFILES" -eq 1 ]' in source


def test_installer_embeds_task_copilot_api_required_by_journey_verifier():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert 'TC_DIR="$SCRIPT_DIR/../tc"' in source
    assert 'pip install --quiet -e "$TC_DIR"' in source
    assert "-c 'import tc.api'" in source


def test_frozen_release_embeds_task_copilot_api_required_by_journey_verifier():
    script = (
        Path(__file__).parents[3] / "scripts/package-cc-macos-release.sh"
    ).read_text(encoding="utf-8")

    assert '${source_checkout}/tools/tc/src' in script
    assert '--hidden-import "tc.api"' in script


@pytest.mark.parametrize("installer", ["cc", "tc"])
def test_installers_reject_python_older_than_3_10_before_touching_anything(
    tmp_path: Path, installer: str
):
    """Fake a 3.9 python3 on PATH; the installer must stop with a clear message
    before creating a virtual environment or shim."""
    script = Path(__file__).parents[2] / installer / "install.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "python3"
    fake.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        '  *version_info*) exit 1 ;;\n'
        '  *--version*) echo "Python 3.9.6" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {"PATH": f"{fake_bin}:/usr/bin:/bin", "HOME": str(home)}

    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "Python 3.10 or newer is required" in result.stderr
    assert "Python 3.9.6" in result.stderr
    assert not (home / ".local").exists()
    assert not (script.parent / ".venv" / "pyvenv.cfg.fake").exists()
