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

# ruff exit codes: 0 clean, 1 violations found, 2 aborted before checking.
# 1 is a statement about the pack; 2 is a statement about the environment, and
# reporting them the same way makes a real finding unrecoverable.
RUFF_ABORTED = 2

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

    relative = [str(path.relative_to(pack_path)) for path in python_files]

    # The pipeline runs two ruff hooks: the linter and the formatter. The
    # formatter matters as much as the linter, because the contribution gate
    # fails whenever a hook modifies a file, so a purely cosmetic difference
    # is a hard CI failure.
    passed = _run_ruff(
        pack_path,
        ["check", "--no-fix", *relative],
        "ruff found issues in Python content",
    )

    formatted = _run_ruff(
        pack_path,
        ["format", "--check", *relative],
        f"Python content is not formatted as the pipeline expects "
        f"(run: spellbook format {pack_path.name})",
    )

    return passed and formatted


def run_ruff_format(pack_path: Path) -> bool:
    """Rewrite the pack's Python with the formatting the pipeline expects.

    The counterpart to the formatter check above. Without this the check
    reports a problem the author has no working way to fix: plain
    `ruff format` uses its own default line length of 88 where this
    configuration uses 130, so following that advice reformats files the
    check had already accepted and makes them fail.

    This is the only place spellbook edits a user's files, and it runs only
    when asked for by name. It applies the formatter alone; lint findings are
    left for the author, since fixing those is a judgement call.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        True if the formatter ran, False if it could not.
    """
    python_files = find_python_files(pack_path)
    if not python_files:
        click.echo(f"[OK] {pack_path.name}: no Python content to format")
        return True

    if shutil.which("ruff") is None:
        click.echo("[ERROR] ruff not found, cannot format")
        return False

    relative = [str(path.relative_to(pack_path)) for path in python_files]

    result = subprocess.run(
        [
            "ruff",
            "format",
            "--config",
            str(RUFF_CONFIG),
            "--force-exclude",
            "--no-cache",
            *relative,
        ],
        capture_output=True,
        text=True,
        cwd=str(pack_path),
    )

    if result.stdout:
        click.echo(result.stdout, nl=False)
    if result.stderr:
        click.echo(result.stderr, nl=False)

    if result.returncode != 0:
        click.echo(
            f"[ERROR] {pack_path.name}: ruff could NOT RUN (format) - it "
            f"exited before formatting anything"
        )
        return False

    click.echo(f"[OK] {pack_path.name}: formatted for the content pipeline")
    return True


def _run_ruff(pack_path: Path, args: list[str], failure_message: str) -> bool:
    """Run one ruff subcommand against the pack, returning True if it passed.

    Runs from the pack directory with relative paths: ruff anchors the
    config's relative per-file-ignores globs in a way that never matches
    absolute paths from outside the config's own tree, so absolute paths
    would silently lose the pipeline's exemptions.
    """
    # --force-exclude makes ruff honour the config's extend-exclude for
    # paths passed explicitly on the command line; without it the pipeline's
    # exemptions (test_data, conftest.py, demistomock.py, CommonServerPython)
    # are silently ignored. The upstream ruff pre-commit hook sets it for the
    # same reason.
    #
    # --no-cache because ruff otherwise writes .ruff_cache into the directory
    # it runs in, which is the user's pack. On a read-only mount it cannot,
    # and it aborts without linting anything; in CI that failed five packs on
    # every push with a message about formatting. The cache is an
    # optimisation, and not writing into a user's content is the same rule
    # the test sandbox follows.
    result = subprocess.run(
        [
            "ruff",
            args[0],
            "--config",
            str(RUFF_CONFIG),
            "--force-exclude",
            "--no-cache",
            *args[1:],
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

    if result.returncode == RUFF_ABORTED:
        click.echo(
            f"[ERROR] {pack_path.name}: ruff could NOT RUN ({args[0]}) - it "
            f"exited before checking anything, so this says nothing about the "
            f"pack's Python"
        )
        return False

    click.echo(f"[ERROR] {pack_path.name}: {failure_message}")
    return False
