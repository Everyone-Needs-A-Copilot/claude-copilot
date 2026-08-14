from pathlib import Path


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


def test_installer_builds_one_noneditable_cc_and_task_copilot_bundle():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert 'TC_DIR="$SCRIPT_DIR/../tc"' in source
    assert '--force-reinstall "$TC_DIR" "$SCRIPT_DIR"' in source
    assert 'pip install --quiet -e "$TC_DIR"' not in source
    assert 'pip install --quiet -e "$SCRIPT_DIR"' not in source
    assert "import tc.api" in source
    assert "from tc.db.connection import find_db_path" in source
    assert 'directory.glob("*.pth")' in source
    assert "editable source path remains" in source


def test_installer_probes_hidden_journey_verifier_outside_ambient_environment():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert "env -i" in source
    assert 'HOME="$PROBE_ROOT/home"' in source
    assert 'cd "$PROBE_ROOT/work"' in source
    assert "journey verify-dispatch" in source
    assert '"state": "no_active"' in source


def test_frozen_release_collects_complete_task_copilot_package():
    script = (
        Path(__file__).parents[3] / "scripts/package-cc-macos-release.sh"
    ).read_text(encoding="utf-8")

    assert "${source_checkout}/tools/tc/src" in script
    assert '--collect-submodules "tc"' in script


def test_frozen_release_probes_exact_artifact_without_checkout_or_pythonpath():
    script = (
        Path(__file__).parents[3] / "scripts/package-cc-macos-release.sh"
    ).read_text(encoding="utf-8")

    build = script.index("run_python -m PyInstaller")
    artifact = script.index('artifact="${pyinstaller_dist}/cc"')
    probe = script.index('"${artifact}" journey verify-dispatch')
    first_network = script.index('"${artifact}" auth login')
    assert build < artifact < probe < first_network
    assert 'cd "${journey_probe_work}"' in script
    assert "env -i" in script
    assert 'HOME="${journey_probe_home}"' in script
    assert 'PATH="/usr/bin:/bin:/usr/sbin:/sbin"' in script
    assert "PYTHONPATH=" not in script[artifact:probe]
    assert '"state": "no_active"' in script[probe:first_network]


def test_readme_documents_supported_framework_bundle_not_standalone_wheel():
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")

    assert "cc + Task Copilot runtime bundle" in readme
    assert "standalone `claude-cli` wheel" in readme
    assert "installs `cc` in editable mode" not in readme
