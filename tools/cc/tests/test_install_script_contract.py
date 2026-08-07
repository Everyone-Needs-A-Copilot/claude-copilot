from pathlib import Path


def test_installer_bootstraps_pip_for_existing_uv_virtual_environment():
    source = (Path(__file__).parents[1] / "install.sh").read_text(encoding="utf-8")

    assert 'if ! "$VENV_DIR/bin/python" -m pip --version' in source
    assert '"$VENV_DIR/bin/python" -m ensurepip --upgrade' in source
    assert source.index("-m ensurepip --upgrade") < source.index(
        '"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip'
    )
