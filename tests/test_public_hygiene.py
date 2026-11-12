"""Bounded public-tree checks. No network, credentials, or model calls."""
import hashlib
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI_SHA256 = "4576223a294403ed8e15536941da5d73110c9f157bbf1bc3a008872dce62260d"
ALLOWED_EMAIL_SUFFIXES = (
    "@users.noreply.github.com",
    "@example.com",
    "@example.org",
    "@example.net",
)
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def tracked_files():
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
    )
    return [ROOT.joinpath(*Path(part.decode()).parts) for part in output.split(b"\0") if part]


class PublicHygieneTests(unittest.TestCase):
    def test_tracked_text_has_no_disallowed_email(self):
        paths = []
        for path in tracked_files():
            if not path.is_file():
                continue
            data = path.read_bytes()
            if b"\0" in data or len(data) > 2_000_000:
                continue
            text = data.decode("utf-8", "replace")
            for match in EMAIL.findall(text):
                if not match.lower().endswith(ALLOWED_EMAIL_SUFFIXES):
                    paths.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(paths, [], "disallowed email-like text in: " + ", ".join(paths))

    def test_p0d_docs_and_disabled_settings(self):
        identity = (ROOT / "docs/automation/P0_IDENTITY.md").read_text()
        security = (ROOT / "docs/automation/P0_SECURITY_SETTINGS.md").read_text()
        for phrase in (
            "Dual identity is not solved.",
            "The pilot stays disabled until it is.",
            "at most one free machine account",
            "classic personal access token",
            "codex-worker@users.noreply.github.com",
            "0600",
            "0700",
        ):
            self.assertIn(phrase, identity)
        for phrase in (
            "USER step",
            "UNVERIFIED",
            "cf-ci-gate",
            "Require branches to be up to date before merging",
            "Do not allow bypassing the above settings",
            "Allow force pushes",
            "Allow deletions",
        ):
            self.assertIn(phrase, security)
        self.assertGreaterEqual(security.count("USER step"), 7)
        settings = json.loads((ROOT / "automation/settings.example.json").read_text())
        self.assertIs(settings["enabled"], False)
        self.assertEqual(settings["canary_issue"], 4)
        digest = hashlib.sha256((ROOT / ".github/workflows/ci.yml").read_bytes()).hexdigest()
        self.assertEqual(digest, CI_SHA256)
