#!/usr/bin/env python3
"""Print a deterministic, read-only fingerprint for one Git worktree candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path, PurePath
from typing import Any


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def git(repo: Path, *args: str, allow_failure: bool = False) -> bytes:
    completed = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True,
        check=False,
    )
    if completed.returncode and not allow_failure:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {error}")
    return completed.stdout if completed.returncode == 0 else b""


def length_prefix(value: bytes) -> bytes:
    return len(value).to_bytes(8, "big") + value


def untracked_manifest(repo: Path, raw_paths: bytes) -> dict[str, Any]:
    path_values = [value for value in raw_paths.split(b"\0") if value]
    manifest = hashlib.sha256()
    rendered_paths: list[str] = []

    for raw_path in sorted(path_values):
        relative = Path(os.fsdecode(raw_path))
        pure = PurePath(relative)
        if relative.is_absolute() or ".." in pure.parts:
            raise RuntimeError(f"unsafe untracked path returned by git: {relative}")
        target = repo / relative
        metadata = target.lstat()
        rendered_paths.append(relative.as_posix())

        if stat.S_ISLNK(metadata.st_mode):
            kind = b"symlink"
            content_hash = sha256(os.fsencode(os.readlink(target))).encode("ascii")
        elif stat.S_ISREG(metadata.st_mode):
            kind = b"file"
            content = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    content.update(chunk)
            content_hash = content.hexdigest().encode("ascii")
        else:
            kind = f"mode:{stat.S_IFMT(metadata.st_mode):o}".encode("ascii")
            content_hash = b""

        manifest.update(length_prefix(raw_path))
        manifest.update(length_prefix(kind))
        manifest.update(length_prefix(content_hash))

    return {
        "count": len(path_values),
        "manifest_sha256": manifest.hexdigest(),
        "paths": rendered_paths,
    }


def fingerprint(repo_arg: Path) -> dict[str, Any]:
    repo = Path(
        git(repo_arg.expanduser().resolve(), "rev-parse", "--show-toplevel")
        .decode("utf-8")
        .strip()
    ).resolve()
    remote_raw = git(repo, "remote", "get-url", "origin", allow_failure=True)
    remote = remote_raw.decode("utf-8", errors="replace").strip() or None
    head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    index = git(repo, "ls-files", "-s", "-z")
    staged = git(
        repo,
        "diff",
        "--cached",
        "--binary",
        "--no-ext-diff",
        "--submodule=short",
    )
    unstaged = git(
        repo,
        "diff",
        "--binary",
        "--no-ext-diff",
        "--submodule=short",
        "--ita-visible-in-index",
    )
    untracked = untracked_manifest(
        repo,
        git(repo, "ls-files", "--others", "--exclude-standard", "-z"),
    )

    identity = {
        "remote": remote,
        "head": head,
        "index_sha256": sha256(index),
        "staged_diff_sha256": sha256(staged),
        "unstaged_diff_sha256": sha256(unstaged),
        "untracked_manifest_sha256": untracked["manifest_sha256"],
    }
    return {
        "schema_version": 1,
        "repo": str(repo),
        **identity,
        "untracked": untracked,
        "dirty": bool(staged or unstaged or untracked["count"]),
        "candidate_sha256": sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = fingerprint(args.repo)
    except (OSError, RuntimeError) as exc:
        print(f"candidate fingerprint failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
