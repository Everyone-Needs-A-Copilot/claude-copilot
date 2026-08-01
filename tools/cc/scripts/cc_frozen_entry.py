"""PyInstaller entry point for the independently signed macOS cc helper."""

import os
from pathlib import Path

import certifi


# The python.org framework build expects its installer to provision a CA
# bundle outside the interpreter. A frozen one-file helper has no such
# machine-global installation step, so make its pinned certifi bundle the
# explicit TLS trust source before any cc module can create an SSL context.
ca_bundle = certifi.where()
if not Path(ca_bundle).is_file():
    raise RuntimeError("the frozen cc helper is missing its CA bundle")
os.environ["SSL_CERT_FILE"] = ca_bundle

from cc.main import app


if __name__ == "__main__":
    app()
