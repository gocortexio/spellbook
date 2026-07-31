# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Pack Unit Test Module

Runs a pack's integration and script unit tests the way the official
demisto/content pipeline does, so a pack that passes validation here does not
then fail the pipeline's test run.

The pipeline runs pytest with three files staged beside the code under test:
demistomock.py, CommonServerPython.py, and a conftest.py whose autouse
fixtures fail any test that writes to stdout or stderr, or logs at WARNING or
above. demisto-sdk does not ship those files (it copies them from a content
checkout, which a Spellbook instance does not have), so they are vendored in
spellbook/assets/pytest_env; see the PROVENANCE.md there.

Tests run against a copy of the package in a temporary sandbox rather than in
the pack itself, so the user's content is never left carrying the scaffolding
or a __pycache__ directory.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import click


PYTEST_ENV_DIR = Path(__file__).parent / "assets" / "pytest_env"

# Staged beside the code under test, matching the pipeline's copy_files step.
SCAFFOLDING = ("demistomock.py", "CommonServerPython.py", "conftest.py")

# Content types whose packages carry Python unit tests.
TESTABLE_CONTENT_DIRS = ("Integrations", "Scripts")

TEST_FILE_SUFFIX = "_test.py"

# A pack's suite should be quick. The cap stops a hanging test from wedging
# validation with no output.
TEST_TIMEOUT_SECONDS = 600


def find_testable_packages(pack_path: Path) -> list[Path]:
    """Return package directories that contain at least one unit test."""
    packages = []
    for content_type in TESTABLE_CONTENT_DIRS:
        content_dir = pack_path / content_type
        if not content_dir.is_dir():
            continue
        for package in sorted(content_dir.iterdir()):
            if not package.is_dir() or package.is_symlink():
                continue
            if any(package.glob(f"*{TEST_FILE_SUFFIX}")):
                packages.append(package)
    return packages


def _stage_sandbox(package: Path, sandbox: Path) -> None:
    """Copy the package and the vendored scaffolding into a sandbox."""
    shutil.copytree(package, sandbox, dirs_exist_ok=True)
    for name in SCAFFOLDING:
        source = PYTEST_ENV_DIR / name
        if source.exists():
            shutil.copyfile(source, sandbox / name)


def run_pack_tests(pack_path: Path) -> bool:
    """Run unit tests for every testable package in the pack.

    Packs with no unit tests pass immediately, which is the common case for
    XSIAM content. Missing scaffolding is reported and skipped rather than
    failing, matching how a missing demisto-sdk or ruff is handled.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        True if every package passed (or there was nothing to run).
    """
    packages = find_testable_packages(pack_path)
    if not packages:
        return True

    missing = [name for name in SCAFFOLDING if not (PYTEST_ENV_DIR / name).exists()]
    if missing:
        click.echo(
            f"[WARN] pytest scaffolding missing ({', '.join(missing)}), "
            f"skipping unit tests"
        )
        return True

    passed = True
    for package in packages:
        if not _run_package_tests(pack_path, package):
            passed = False
    return passed


def _run_package_tests(pack_path: Path, package: Path) -> bool:
    """Run one package's tests in a sandbox, returning True if they passed."""
    workdir = Path(tempfile.mkdtemp(prefix="spellbook_tests_"))
    sandbox = workdir / package.name
    try:
        _stage_sandbox(package, sandbox)

        env = os.environ.copy()
        # The sandbox holds demistomock and CommonServerPython, which the
        # code under test imports by bare name.
        env["PYTHONPATH"] = str(sandbox)
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "."],
                cwd=str(sandbox),
                env=env,
                capture_output=True,
                text=True,
                timeout=TEST_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            click.echo(
                f"[ERROR] {pack_path.name}: unit tests for {package.name} exceeded "
                f"{TEST_TIMEOUT_SECONDS}s and were stopped"
            )
            return False
        except FileNotFoundError:
            click.echo("[WARN] pytest not found, skipping unit tests")
            return True

        if result.returncode == 0:
            return True

        if result.stdout:
            click.echo(result.stdout, nl=False)
        if result.stderr:
            click.echo(result.stderr, nl=False)
        click.echo(
            f"[ERROR] {pack_path.name}: unit tests failed for {package.name} "
            f"(the official content pipeline runs these same tests)"
        )
        return False
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
