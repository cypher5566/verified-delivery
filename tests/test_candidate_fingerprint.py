from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "candidate_fingerprint.py"


class CandidateFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        self.git("init")
        self.git("config", "user.email", "verified-delivery@example.invalid")
        self.git("config", "user.name", "verified-delivery test")
        (self.repo / "tracked.txt").write_text("one\n", encoding="utf-8")
        self.git("add", "tracked.txt")
        self.git("commit", "-m", "initial")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            check=True,
        )

    def fingerprint(self) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(self.repo)],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_clean_candidate_is_stable(self) -> None:
        first = self.fingerprint()
        second = self.fingerprint()
        self.assertFalse(first["dirty"])
        self.assertIsNone(first["remote"])
        self.assertEqual(first["candidate_sha256"], second["candidate_sha256"])
        self.assertEqual(first["untracked"]["count"], 0)

    def test_staged_and_unstaged_changes_alter_candidate(self) -> None:
        clean = self.fingerprint()
        (self.repo / "tracked.txt").write_text("two\n", encoding="utf-8")
        unstaged = self.fingerprint()
        self.assertTrue(unstaged["dirty"])
        self.assertNotEqual(clean["candidate_sha256"], unstaged["candidate_sha256"])

        self.git("add", "tracked.txt")
        staged = self.fingerprint()
        self.assertNotEqual(
            unstaged["candidate_sha256"],
            staged["candidate_sha256"],
        )
        self.assertNotEqual(clean["index_sha256"], staged["index_sha256"])

    def test_untracked_content_alters_manifest_without_exposing_content(self) -> None:
        path = self.repo / "new.txt"
        path.write_text("secret-one\n", encoding="utf-8")
        first = self.fingerprint()
        path.write_text("secret-two\n", encoding="utf-8")
        second = self.fingerprint()

        self.assertEqual(first["untracked"]["paths"], ["new.txt"])
        self.assertNotEqual(
            first["untracked"]["manifest_sha256"],
            second["untracked"]["manifest_sha256"],
        )
        self.assertNotIn("secret-one", json.dumps(first))

    def test_untracked_symlink_target_alters_manifest(self) -> None:
        path = self.repo / "new-link"
        path.symlink_to("first-target")
        first = self.fingerprint()
        path.unlink()
        path.symlink_to("second-target")
        second = self.fingerprint()

        self.assertEqual(first["untracked"]["paths"], ["new-link"])
        self.assertNotEqual(
            first["untracked"]["manifest_sha256"],
            second["untracked"]["manifest_sha256"],
        )

    def test_dirty_submodule_requires_its_own_fingerprint_for_identity(self) -> None:
        with tempfile.TemporaryDirectory() as source_directory:
            source = Path(source_directory)
            subprocess.run(
                ["git", "-C", str(source), "init"],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "config",
                    "user.email",
                    "verified-delivery@example.invalid",
                ],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(source),
                    "config",
                    "user.name",
                    "verified-delivery test",
                ],
                capture_output=True,
                check=True,
            )
            (source / "child.txt").write_text("one\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(source), "add", "child.txt"],
                capture_output=True,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(source), "commit", "-m", "child"],
                capture_output=True,
                check=True,
            )
            self.git(
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(source),
                "vendor/child",
            )
            self.git("commit", "-m", "add submodule")

            parent_clean = self.fingerprint()
            child = self.repo / "vendor" / "child"
            (child / "child.txt").write_text("two\n", encoding="utf-8")
            parent_dirty = self.fingerprint()
            child_first = self.fingerprint_for(child)
            (child / "child.txt").write_text("three\n", encoding="utf-8")
            child_second = self.fingerprint_for(child)

        self.assertNotEqual(
            parent_clean["candidate_sha256"],
            parent_dirty["candidate_sha256"],
        )
        self.assertNotEqual(
            child_first["candidate_sha256"],
            child_second["candidate_sha256"],
        )

    def fingerprint_for(self, repo: Path) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo)],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
