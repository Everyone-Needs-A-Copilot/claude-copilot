"""The reviewed Claude migration must not silently authorize another product."""

import re
import subprocess
from pathlib import Path

from cc.commands.onboard import FOUNDATION_ALLOWED_SIGNERS
from cc.core.ecosystem.policy import FOUNDATION_SSH_SIGNING_KEYS

NEW = "SHA256:Dg6yz1MZ4IgBlm+E1TAC49FlVbQ4aaEsvDY7wHNPG5s"
OLD = "SHA256:FIfppOkzwXZUAamELQzYoSUQXiEAmTYiVewHe1ACMZo"
ROOT = Path(__file__).parents[3]


def test_compiled_keys_match_reviewed_fingerprints(tmp_path):
    for fingerprint in (NEW, OLD):
        public_key = tmp_path / "key.pub"
        public_key.write_text(FOUNDATION_SSH_SIGNING_KEYS[fingerprint.upper()] + "\n")
        actual = subprocess.run(
            ["ssh-keygen", "-lf", str(public_key), "-E", "sha256"],
            capture_output=True, text=True, check=True,
        ).stdout.split()[1]
        assert actual == fingerprint


def test_claude_migration_does_not_change_codex_authority():
    assert FOUNDATION_ALLOWED_SIGNERS["claude"] == (NEW, OLD)
    assert FOUNDATION_ALLOWED_SIGNERS["codex"] == (OLD,)
    assert FOUNDATION_ALLOWED_SIGNERS["cli"] == ()
    assert FOUNDATION_ALLOWED_SIGNERS["knowledge"] == ()


def test_release_preflight_defaults_to_same_reviewed_key():
    script = (ROOT / "scripts/verify-foundation-release.sh").read_text()
    default = re.search(r'public_key="\$\{FOUNDATION_RELEASE_PUBLIC_KEY:-(.*?)\}"', script)
    assert default is not None
    assert default.group(1) == FOUNDATION_SSH_SIGNING_KEYS[NEW.upper()]
