#!/usr/bin/env python3
"""Run one argv-only command under a fixed macOS Seatbelt deny-write boundary."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path


def decode(value: str, label: str) -> object:
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid {label}: {exc}") from exc


def seatbelt_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deny-write-base64", required=True)
    parser.add_argument("--argv-base64", required=True)
    args = parser.parse_args()

    deny_write = decode(args.deny_write_base64, "deny-write path")
    command = decode(args.argv_base64, "command argv")
    if not isinstance(deny_write, str) or not deny_write:
        raise SystemExit("deny-write path must decode to a non-empty string")
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item for item in command
    ):
        raise SystemExit("command must decode to a non-empty string argv list")

    protected = Path(deny_write).expanduser().resolve(strict=True)
    if not protected.is_dir():
        raise SystemExit(f"deny-write path is not a directory: {protected}")
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    if sys.platform != "darwin" or not sandbox_exec.is_file():
        raise SystemExit("the fixed Seatbelt runner is available only on macOS")

    profile = (
        '(version 1) (allow default) (deny file-write* (subpath "'
        + seatbelt_quote(str(protected))
        + '"))'
    )
    print(f"seatbelt deny-write: {protected}", file=sys.stderr)
    print(f"seatbelt argv: {json.dumps(command, ensure_ascii=False)}", file=sys.stderr)
    try:
        completed = subprocess.run(
            [str(sandbox_exec), "-p", profile, "/usr/bin/env", *command],
            check=False,
        )
    except OSError as exc:
        print(f"cannot start Seatbelt command: {exc}", file=sys.stderr)
        return 127
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
