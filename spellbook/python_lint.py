# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Python Lint Module

Runs ruff over a pack's Python content using the same configuration the
official demisto/content store pipeline applies, so a pack that builds
clean here does not then fail store submission on lint findings.

The store pipeline runs ruff through `demisto-sdk pre-commit`. That command
cannot be wrapped here: it resolves its CONTENT_PATH at import time, so a
path passed by a calling process arrives too late and the command aborts.
Spellbook therefore invokes ruff directly, with a vendored copy of the
pipeline's configuration in assets/ruff_parity.toml. The ruff version is
pinned in pyproject.toml to match the pipeline's own pin.
"""

import shutil
import subprocess
from pathlib import Path

import click


RUFF_CONFIG = Path(__file__).parent / "assets" / "ruff_parity.toml"

# Generated demisto-sdk support files. They are gitignored in content
# instances and never reach the store pipeline, so linting them would only
# produce findings the pipeline cannot see.
EXCLUDED_FILENAMES = {
    "demistomock.py",
    "CommonServerPython.py",
    "CommonServerUserPython.py",
}


def find_python_files(pack_path: Path) -> list[Path]:
    """Return the pack's lintable Python files, sorted for stable output."""
    return sorted(
        path
        for path in pack_path.rglob("*.py")
        if path.is_file()
        and not path.is_symlink()
        and path.name not in EXCLUDED_FILENAMES
    )


def run_ruff_check(pack_path: Path) -> bool:
    """Lint the pack's Python files with the store parity configuration.

    Packs without Python content pass immediately. A missing ruff binary
    is reported and skipped rather than failing, matching how a missing
    demisto-sdk is handled during validation.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        True if there were no findings (or nothing to lint), False otherwise.
    """
    python_files = find_python_files(pack_path)
    if not python_files:
        return True

    if shutil.which("ruff") is None:
        click.echo("[WARN] ruff not found, skipping Python lint")
        return True

    # Run from the pack directory with relative paths. ruff anchors the
    # config's relative per-file-ignores globs (e.g. **/test_data/*) in a
    # way that never matches absolute paths outside the config's own tree;
    # relative paths restore the store pipeline's matching behaviour.
    result = subprocess.run(
        [
            "ruff",
            "check",
            "--config",
            str(RUFF_CONFIG),
            *[str(path.relative_to(pack_path)) for path in python_files],
        ],
        capture_output=True,
        text=True,
        cwd=str(pack_path),
    )

    if result.returncode == 0:
        return True

    if result.stdout:
        click.echo(result.stdout, nl=False)
    if result.stderr:
        click.echo(result.stderr, nl=False)
    click.echo(
        f"[ERROR] {pack_path.name}: ruff found issues in Python content "
        f"(the official demisto/content pipeline enforces these rules)"
    )
    return False
