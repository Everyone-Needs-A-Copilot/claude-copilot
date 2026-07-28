"""Regression coverage for the independently packaged macOS helper."""

import os
import runpy
from pathlib import Path

import certifi


def test_frozen_entry_configures_bundled_ca_before_loading_cli(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)

    entry_point = (
        Path(__file__).resolve().parents[1] / "scripts" / "cc_frozen_entry.py"
    )
    runpy.run_path(entry_point, run_name="cc_frozen_entry_test")

    ca_bundle = Path(os.environ["SSL_CERT_FILE"])
    assert ca_bundle == Path(certifi.where())
    assert ca_bundle.is_file()
