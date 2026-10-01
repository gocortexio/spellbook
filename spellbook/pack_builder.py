# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Pack Builder Module

Handles discovery, validation, and packaging of Cortex Platform content packs.
"""

import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import click

from .pack_template import DEFAULT_CONTRIBUTORS
import yaml

from .pack_tests import run_pack_tests
from .python_lint import run_ruff_check
from .version_manager import VersionManager
from .xsiam_validator import ValidationIssue, check_docker_images, render_issue


EXCLUDED_PACKS = ["SamplePack"]


# demisto-sdk's default_config.toml selects only these 15 codes for a path-based
# run, which is what `-i` resolves to. Restated here because `-sv` REPLACES the
# config's select rather than extending it (validate/config_reader.py:
# `select = explicitly_selected or sorted(section.get("select", []))`), so
# passing only the additions below would silently switch these 15 off and weaken
# the gate while appearing to strengthen it.
SDK_DEFAULT_VALIDATIONS = [
    "BA101", "BA105", "BA106", "BA116", "BA118", "DO104", "IN108", "IN130",
    "PA107", "PA108", "PA111", "PA115", "PA128", "PA130", "RP101",
]

# Validators the pinned SDK ships but its default config never selects. Each one
# corresponds to a finding the marketplace review bot raised against a pack that
# spellbook had already passed, so every one of these is a gap this gate had.
#
# Enabled rather than reimplemented: BA131's valid-module vocabulary changed
# between SDK 1.38 and 1.39, so a hand-written copy would rot against the pin.
SDK_ADDITIONAL_VALIDATIONS = [
    "ST111",   # missing `sectionorder` root key and per-parameter `section`
    "BA133",   # event collector without an isFetchEvents parameter
    "DS108",   # descriptions must end with a period
    "RM110",   # every command must appear in the README
    "RM102",   # README and YAML must agree on context outputs
    "IN169",   # integration missing the `provider` field
    "MR108",   # modelling rule id/name must carry the required suffixes
]

# MR108 closes an inconsistency of our own rather than only an upstream gap.
# `summon datamodel` already refuses to CREATE a rule whose stem breaks MR108
# (rule_importer._validate_stem), so spellbook would not let an author write the
# violation while happily shipping packs that already contained it.
#
# Two upstream codes were measured and deliberately NOT selected:
#
#   ST110 - fires 27 times on one pack, every hit "suppression_fields: str type
#           expected". That is the false positive this module already documents
#           and filters (LIST_TOLERANT_FIELDS): the strict model declares the
#           field a string, the platform stores an array, and demisto-sdk itself
#           accepts one. Selecting it would reintroduce a finding already judged
#           wrong.
#   ST114 - reports the same licence codes BA133 already reports. Redundant, and
#           a second finding for one defect reads as two defects.

# BA131 (supportedModules) is deliberately NOT selected, despite the review bot
# raising it. It fires on two different things and only one of them is ours:
#
#   - a real defect, where an integration .yml declares licence codes such as
#     C1 / X1 / ENT_PLUS instead of module names, and
#   - an absence, where a correlation or modelling rule declares no
#     supportedModules at all, the SDK defaults the item to every module, and
#     BA131 then rejects that default as a superset of what the item type allows.
#
# Measured across the 24 packs in the content estate, the second case accounts
# for the finding in 20 of them - including packs with no integration at all.
# Selecting it would fail validate on packs whose files do not contain the word
# supportedModules anywhere, for a value they never wrote. Revisit if the estate
# ever declares supportedModules explicitly on rule items.

# SDK defaults that spellbook checks natively instead of selecting, mapped to
# the function that stands in for each. validate_pack runs every one of them
# inside the demisto-sdk stage, where the code it replaces ran, so a stand-in
# blocks exactly what its SDK code blocked: build, validate and validate-all,
# and not upload, which never ran the SDK's validators. Running one with the
# other xsiam_validator checks instead made it advisory in build, which only
# prints those - a pack DO104 failed would then build and exit 0.
#
# DO104 (Python and PowerShell content must name a docker image) cannot run on a
# pack holding a prompt-backed script:
#
#   - a prompt script (`isllm: true`) runs no code and has no container, which
#     DO104 does not know, so it reports the script as missing an image;
#   - before it can say so, it asks Docker Hub for the newest image of
#     demisto/<subtype> to name in the message. A prompt script's
#     `type: python` carries no subtype, the SDK assumes python2, and there is
#     no demisto/python2 on Docker Hub - demisto's Python 2 image is
#     demisto/python - so the anonymous lookup gets a 401. It raises instead of
#     failing the item, so the whole SDK run dies and no validator reports.
#
# Measured on a real agent pack: every run crashed, and adding `subtype:
# python3` turned the crash into a false DO104 error. Unchanged upstream as of
# SDK 1.39.10. The native rule (missing_docker_image) keeps DO104's condition
# and reach, adds only the prompt exemption, and needs no network - where DO104
# needed Docker Hub to report any finding at all.
SDK_DEFAULTS_CHECKED_NATIVELY = {
    "DO104": check_docker_images,
}

SDK_SELECTED_VALIDATIONS = [
    code for code in SDK_DEFAULT_VALIDATIONS
    if code not in SDK_DEFAULTS_CHECKED_NATIVELY
] + SDK_ADDITIONAL_VALIDATIONS

# How a demisto-sdk run that failed is told apart from one that crashed: a
# failed run printed at least one finding line (SDK_FINDING_LINE_PATTERN,
# below), and a crashed one printed none, so it reported nothing an author or
# agent can act on. Anchored to the whole line shape, not to a bare `[XX000]`,
# which an exception message can quote.
SDK_TRACEBACK_HEADER = "Traceback (most recent call last):"
SDK_EXCEPTION_GROUP_HEADER = "Exception Group Traceback (most recent call last):"
# Every line of an exception group's traceback is prefixed with `|`.
SDK_EXCEPTION_GROUP_PREFIX = re.compile(r"^\s*\| ?")
# A traceback frame inside a validator module names the validator that raised.
SDK_VALIDATOR_FRAME_PATTERN = re.compile(
    r"validators[\\/][A-Z]{2}_validators[\\/]([A-Z]{2}\d{3})_"
)
# An exception line can carry a whole URL or response body.
SDK_CRASH_DETAIL_LIMIT = 300
SDK_CRASH_RULE = "sdk_crashed"
# One demisto-sdk finding, as it prints it: `<path>: [DS108] - <message>`.
SDK_FINDING_LINE_PATTERN = re.compile(
    r"^(?P<path>\S.*?): \[(?P<code>[A-Z]{2}\d{3})\] - (?P<message>.*)$", re.M
)

# How long to let HEAD settle before believing it does not resolve. On a Docker
# Desktop bind mount a commit made on the host moments before the container
# starts is often unreadable for a fraction of a second - measured at 4 of 5
# immediate reads - and a single read reported a committed repository as having
# no commit. Past a second it resolved every time.
HEAD_RESOLVE_ATTEMPTS = 5
HEAD_RESOLVE_DELAY_SECONDS = 0.5

# demisto-sdk colours its finding lines even into a pipe, and the escapes
# landed in --json as `"\x1b[31mPacks/..."` paths, so they are stripped before
# parsing. Its own switch, DEMISTO_SDK_LOG_NO_COLORS, is no fix: in 1.39.5 it
# prints the logger's markup literally instead, `<red>Packs/...`.
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# The stages validate_pack runs, as named in validate --json's failed_stages.
STAGE_PYTHON_LINT = "python-lint"
STAGE_UNIT_TESTS = "unit-tests"
STAGE_SDK = "demisto-sdk"


def parse_sdk_findings(output: str, packs_dirname: str = "Packs") -> list[ValidationIssue]:
    """Return demisto-sdk's own finding lines as findings.

    Text output already carries them in the SDK's shape, which the SDK prints
    itself; this is for validate --json, which otherwise reported
    failed_stages ["demisto-sdk"] with nothing in `issues` to say why. The
    SDK's code is the rule_name, being the stable identifier it already is.

    Args:
        output: The SDK's combined stdout and stderr.
        packs_dirname: The packs directory name, stripped from paths so they
            read like every other finding's (<Pack>/...).

    Returns:
        One finding per SDK finding line, in the order printed.
    """
    findings = []
    output = ANSI_ESCAPE_PATTERN.sub("", output)
    for match in SDK_FINDING_LINE_PATTERN.finditer(output):
        parts = Path(match.group("path")).parts
        if len(parts) > 1 and parts[0] == packs_dirname:
            parts = parts[1:]
        findings.append(ValidationIssue(
            rule_name=match.group("code"),
            severity="error",
            file_path=str(Path(*parts)),
            message=match.group("message").strip(),
            consequence=(
                "demisto-sdk's gate fails the pack on it, as the official "
                "content pipeline does"
            ),
            remediation=(
                "the message states what the validator requires; fix the named "
                "file and re-run. The rule_name is the demisto-sdk code to "
                "look up"
            ),
        ))
    return findings


def _fatal_traceback(output: str) -> tuple[str, str]:
    """Return the exception that stopped the run, and the validator it was in.

    The LAST traceback is the fatal one - a chained exception prints several,
    and the first was handled. A traceback Python printed as "Exception ignored
    in ..." (an atexit hook, a destructor) was survived, so it is skipped. An
    exception group's lines carry a `|` prefix, which is removed so its
    structure reads like any other traceback's.

    The validator is named only from a frame of the fatal traceback that is
    not import-time (`in <module>`): demisto-sdk imports every validator module
    at start-up whatever is selected, so a module that fails to load has not
    been run against any item. And only a selected validator is named, since
    a frame in an unselected one is a helper it lent, not the check that ran.

    Returns:
        (exception line, validator code); either may be "".
    """
    lines = output.splitlines()
    headers = []
    for number, line in enumerate(lines):
        bare = line.strip().lstrip("+ ")
        is_group = bare.startswith(SDK_EXCEPTION_GROUP_HEADER)
        if not (line.startswith(SDK_TRACEBACK_HEADER) or is_group):
            continue
        previous = next(
            (lines[k].strip() for k in range(number - 1, -1, -1) if lines[k].strip()),
            "",
        )
        if previous.startswith("Exception ignored"):
            continue
        headers.append((number, is_group))
    if not headers:
        return "", ""

    start, is_group = headers[-1]
    block = lines[start + 1:]
    if is_group:
        block = [SDK_EXCEPTION_GROUP_PREFIX.sub("", line) for line in block]

    exception = ""
    frames = []
    for line in block:
        if not line.strip():
            continue
        if line[0].isspace():
            frames.append(line)
            continue
        # loguru's backtrace marks a frame with an unindented `> File ...`,
        # and a group draws its separators with `+`; neither is the exception.
        if line.startswith((">", "+")):
            continue
        exception = line.strip()
        break

    validator = ""
    for frame in frames:
        if frame.rstrip().endswith("in <module>"):
            continue
        match = SDK_VALIDATOR_FRAME_PATTERN.search(frame)
        if match and match.group(1) in SDK_SELECTED_VALIDATIONS:
            validator = match.group(1)
    return exception, validator


def describe_sdk_failure(pack_name: str, returncode: int, output: str) -> ValidationIssue | None:
    """Return a finding for a demisto-sdk run that failed without reporting one.

    A non-zero exit that printed at least one `[XX000]` finding is an ordinary
    failure, and the SDK's own lines already name the file and the code. A
    non-zero exit that printed none is the SDK failing to finish. That used to
    surface as a raw traceback and "Validation failed for <pack>", with no
    tagged line and nothing in --json - so an agent fixed whatever else was
    listed, re-ran, hit the same wall, and had nothing to key on.

    Args:
        pack_name: The pack being validated.
        returncode: The SDK's exit status.
        output: Its stdout and stderr, combined.

    Returns:
        The finding, or None when the run passed or reported findings of its own.
    """
    output = ANSI_ESCAPE_PATTERN.sub("", output)
    if returncode == 0 or SDK_FINDING_LINE_PATTERN.search(output):
        return None

    def clip(text: str) -> str:
        if len(text) <= SDK_CRASH_DETAIL_LIMIT:
            return text
        return text[:SDK_CRASH_DETAIL_LIMIT] + "..."

    lines = output.splitlines()
    # A killed run is described as killed even when an earlier, handled
    # traceback is in the output: that traceback did not stop it.
    exception, validator = ("", "") if returncode < 0 else _fatal_traceback(output)

    consequence = (
        "none of demisto-sdk's checks reported, so the pack is unvalidated "
        "rather than failed on a finding; fixing unrelated issues will not "
        "clear this unless the exception names one of their files"
    )
    do_not_route_around = "Do not edit valid content to route around it."

    if exception:
        where = f" in {validator}" if validator else ""
        message = f"demisto-sdk crashed{where} before reporting any finding: {clip(exception)}"
        remediation = "the exception names the cause. "
        if validator:
            remediation += (
                f"It was raised inside {validator}, so an item {validator} "
                f"checks triggered it. "
            )
        remediation += (
            "If it points at a file in this pack, check that file is "
            "well-formed; otherwise it is a fault in demisto-sdk or its "
            "environment - re-run once, and if it repeats, report it with the "
            f"output above. {do_not_route_around}"
        )
    elif returncode < 0:
        message = (
            f"demisto-sdk was killed by signal {-returncode} before reporting "
            f"any finding"
        )
        remediation = (
            "a killed validator run is most often out of memory in the "
            "container; give it more memory and re-run"
        )
    else:
        last = next((line.strip() for line in reversed(lines) if line.strip()), "")
        message = f"demisto-sdk exited with code {returncode} without reporting any finding"
        if last:
            message += f": {clip(last)}"
        remediation = (
            "demisto-sdk printed no traceback, so its output above is all the "
            "detail there is; re-run once, and if it repeats, report it with "
            f"that output. {do_not_route_around}"
        )

    return ValidationIssue(
        rule_name=SDK_CRASH_RULE,
        severity="error",
        file_path=pack_name,
        message=message,
        consequence=consequence,
        remediation=remediation,
    )


class UnreadablePackMetadata(Exception):
    """A pack_metadata.json exists but cannot be parsed.

    Raised rather than warned, because the caller that swallowed it went on to
    WRITE. read_pack_metadata used to return a synthetic
    {"name": ..., "currentVersion": "1.0.0"} stub on a parse error, and
    update_pack_metadata then applied its changes to that stub and dumped it
    over the real file - deleting description, support, author, categories,
    tags, useCases, keywords, marketplaces and dependencies, and regressing the
    version, while printing [OK] and exiting 0.

    One trailing comma in a hand-edited file was enough. An empty file did it
    with no warning at all, because the emptiness check fell through to the
    same stub silently.

    The invariant this restores: never write a document that was not
    successfully read.
    """


class PackBuilder:
    """Builds and packages Cortex Platform content packs."""

    def __init__(self, config_path: str = "spellbook.yaml"):
        """
        Initialise the pack builder.

        Args:
            config_path: Path to the spellbook configuration file.
        """
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent if self.config_path.parent != Path(".") else Path(".")
        self.config = self._load_config(config_path)
        # What the most recent validate_pack call found, and which of its
        # stages failed. The boolean it returns cannot carry either, and a
        # --json caller needs them as data rather than as prose on stderr.
        self.last_stage_issues: list[ValidationIssue] = []
        self.last_failed_stages: list[str] = []

        repo_root = self.base_dir.resolve()

        raw_packs_dir = self.config.get("packs_directory", "Packs")
        resolved_packs = (self.base_dir / raw_packs_dir).resolve()
        try:
            resolved_packs.relative_to(repo_root)
        except ValueError:
            raise ValueError(
                f"packs_directory '{raw_packs_dir}' resolves outside the content repository"
            )
        self.packs_dir = resolved_packs

        raw_artifacts_dir = self.config.get("artifacts_directory", "artifacts")
        resolved_artifacts = (self.base_dir / raw_artifacts_dir).resolve()
        try:
            resolved_artifacts.relative_to(repo_root)
        except ValueError:
            raise ValueError(
                f"artifacts_directory '{raw_artifacts_dir}' resolves outside the content repository"
            )
        self.artifacts_dir = resolved_artifacts

        self.version_manager = VersionManager(
            self.config.get("version_tag_pattern", "{pack_name}-v{version}")
        )

    def _load_config(self, config_path: str) -> dict:
        """Load configuration from YAML file."""
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}
    
    def check_config_exists(self) -> bool:
        """Check if the configuration file exists."""
        return self.config_path.exists()
    
    def check_packs_dir_exists(self) -> bool:
        """Check if the Packs directory exists."""
        return self.packs_dir.exists()

    def discover_packs(self) -> list[str]:
        """
        Discover all content packs in the packs directory.

        Returns:
            List of pack names found.
        """
        if not self.packs_dir.exists():
            return []

        packs = []
        exclude = self.config.get("exclude_packs", [])
        exclude_set = set(exclude + EXCLUDED_PACKS)

        for item in self.packs_dir.iterdir():
            if item.is_dir() and item.name not in exclude_set:
                metadata_file = item / "pack_metadata.json"
                if metadata_file.exists():
                    packs.append(item.name)

        return sorted(packs)

    def get_pack_path(self, pack_name: str) -> Path:
        """Get the full path to a pack directory.

        Raises:
            ValueError: If pack_name traverses outside the packs directory.
        """
        candidate = (self.packs_dir / pack_name).resolve()
        try:
            candidate.relative_to(self.packs_dir.resolve())
        except ValueError:
            raise ValueError(
                f"pack_name '{pack_name}' resolves outside the packs directory"
            )
        return candidate

    def pack_exists(self, pack_name: str) -> bool:
        """
        Check if a pack exists and has valid metadata.

        Args:
            pack_name: Name of the pack to check.

        Returns:
            True if pack exists with pack_metadata.json, False otherwise.
        """
        pack_path = self.get_pack_path(pack_name)
        metadata_path = pack_path / "pack_metadata.json"
        return pack_path.exists() and metadata_path.exists()

    def validate_pack_exists(self, pack_name: str) -> None:
        """
        Validate that a pack exists, raising a friendly error if not.

        Args:
            pack_name: Name of the pack to validate.

        Raises:
            SystemExit: If pack does not exist or pack_name is invalid.
        """
        try:
            exists = self.pack_exists(pack_name)
        except ValueError as exc:
            click.echo(f"[ERROR] Invalid pack name: {exc}")
            raise SystemExit(1)
        if not exists:
            available = self.discover_packs()
            click.echo(f"[ERROR] Pack '{pack_name}' not found")
            if available:
                click.echo(f"Available packs: {', '.join(available)}")
            else:
                click.echo("No packs found in Packs/ directory")
            raise SystemExit(1)

    # Organisation-level facts that should be identical in every pack. Each is
    # already sourced from spellbook.yaml at creation time; this carries the same
    # values into packs that were created before the value was configured.
    #
    # Deliberately excludes categories (a per-pack decision, and an empty one is
    # already an error), and author/tags/useCases/keywords/support/marketplaces,
    # any of which a pack could legitimately want to differ on.
    SYNCABLE_METADATA_FIELDS = ("url", "email", "githubUser")

    def sync_pack_defaults(self, pack_name: str, apply: bool = False) -> list[dict]:
        """Carry configured identity values into a pack that predates them.

        Fills only what is EMPTY. A pack holding a different value keeps it and
        the difference is reported instead, because the alternative - making
        config the single source of truth - would silently discard a deliberate
        per-pack choice with no way to opt out.

        Args:
            pack_name: Name of the pack.
            apply: Write the changes. False reports what would change and
                touches nothing.

        Returns:
            One record per field considered, each with an action of "fill",
            "differs" or "set".
        """
        pack_path = self.get_pack_path(pack_name)
        metadata = self.read_pack_metadata(pack_name)
        changes: list[dict] = []
        updates: dict = {}

        for field in self.SYNCABLE_METADATA_FIELDS:
            configured = self.config.get("defaults", {}).get(field)
            if configured in (None, "", []):
                continue

            current = metadata.get(field)
            if current in (None, "", []):
                action = "fill"
                updates[field] = configured
            elif current != configured:
                action = "differs"
            else:
                action = "set"

            changes.append({
                "pack": pack_name,
                "field": field,
                "action": action,
                "current": current,
                "configured": configured,
            })

        # CONTRIBUTORS.json is a sibling file rather than a metadata field, but
        # it is the same kind of fact and the same fill-only rule applies.
        contributors_path = pack_path / "CONTRIBUTORS.json"
        current_contributors = None
        if contributors_path.is_file():
            try:
                current_contributors = json.loads(
                    contributors_path.read_text(encoding="utf-8-sig")
                )
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                current_contributors = None

        default_contributors = list(DEFAULT_CONTRIBUTORS)
        if not current_contributors:
            contributors_action = "fill"
        elif current_contributors != default_contributors:
            contributors_action = "differs"
        else:
            contributors_action = "set"

        changes.append({
            "pack": pack_name,
            "field": "CONTRIBUTORS.json",
            "action": contributors_action,
            "current": current_contributors,
            "configured": default_contributors,
        })

        if apply:
            if updates:
                self.update_pack_metadata(pack_name, updates)
            if contributors_action == "fill":
                with open(contributors_path, "w", encoding="utf-8") as handle:
                    json.dump(default_contributors, handle, indent=4)
                    handle.write("\n")

        return changes

    def read_pack_metadata(self, pack_name: str) -> dict:
        """
        Read pack metadata from pack_metadata.json.

        Args:
            pack_name: Name of the pack.

        Returns:
            Dictionary containing pack metadata.
        """
        metadata_path = self.get_pack_path(pack_name) / "pack_metadata.json"

        if not metadata_path.exists():
            # A genuinely absent file has nothing to lose, so a stub is safe
            # and lets `create`-adjacent paths proceed.
            return {"name": pack_name, "currentVersion": "1.0.0"}

        try:
            with open(metadata_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as error:
            raise UnreadablePackMetadata(
                f"{metadata_path}: could not be read ({error})"
            ) from error

        if not content.strip():
            raise UnreadablePackMetadata(f"{metadata_path}: is empty")

        try:
            return json.loads(content)
        except json.JSONDecodeError as error:
            raise UnreadablePackMetadata(
                f"{metadata_path}: is not valid JSON ({error})"
            ) from error

    def update_pack_metadata(
        self,
        pack_name: str,
        updates: dict
    ) -> None:
        """
        Update pack metadata file.

        Args:
            pack_name: Name of the pack.
            updates: Dictionary of fields to update.
        """
        metadata_path = self.get_pack_path(pack_name) / "pack_metadata.json"
        metadata = self.read_pack_metadata(pack_name)
        
        if "name" not in metadata or not metadata["name"]:
            metadata["name"] = pack_name
            
        metadata.update(updates)

        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.write("\n")

    def update_pack_version(
        self,
        pack_name: str,
        version: str | None = None
    ) -> str:
        """
        Update pack version based on Git tags or specified version.

        Args:
            pack_name: Name of the pack.
            version: Specific version to set, or None for auto-detection.

        Returns:
            The version that was set.
        """
        if version is None:
            version = self.version_manager.get_latest_version(pack_name)

        self.update_pack_metadata(pack_name, {"currentVersion": version})
        return version

    def validate_pack(self, pack_name: str, quiet: bool = False) -> bool:
        """
        Validate a pack using demisto-sdk.

        Args:
            pack_name: Name of the pack to validate.
            quiet: Send human-readable output to stderr instead of stdout, so
                a caller emitting JSON on stdout produces a parseable document.

        Returns:
            True if validation passed, False otherwise. Every failure is
            also left as a finding in self.last_stage_issues, and the stages
            that failed in self.last_failed_stages.
        """
        # Reset before any early return, so a caller never reads a previous
        # pack's findings as this one's.
        self.last_stage_issues = []
        self.last_failed_stages = []
        validation_config = self.config.get("validation", {})
        if not validation_config.get("enabled", True):
            click.echo(f"Validation disabled, skipping {pack_name}", err=quiet)
            return True

        pack_path = self.get_pack_path(pack_name)

        # Lint Python content with the store pipeline's ruff configuration.
        # demisto-sdk validate does not run ruff, so without this a pack can
        # build clean locally and then fail official store submission.
        ruff_passed = run_ruff_check(pack_path, issues=self.last_stage_issues)
        if not ruff_passed:
            self.last_failed_stages.append(STAGE_PYTHON_LINT)

        # Run the pack's own unit tests the way the pipeline does. Same
        # reasoning as the lint above: validate does not run them, so a pack
        # could pass here and fail the pipeline's test stage.
        tests_passed = run_pack_tests(pack_path, issues=self.last_stage_issues)
        if not tests_passed:
            self.last_failed_stages.append(STAGE_UNIT_TESTS)

        content_root = pack_path.parent.parent.resolve()
        
        git_dir = content_root / ".git"
        git_initialised = False
        if not git_dir.exists():
            click.echo("Setting up temporary git repository for validation...", err=quiet)
            try:
                subprocess.run(
                    ["git", "init"],
                    cwd=str(content_root),
                    capture_output=True,
                    check=True
                )
                git_initialised = True
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=str(content_root),
                    capture_output=True,
                    check=True
                )
                subprocess.run(
                    ["git", "-c", "user.name=Spellbook", "-c", "user.email=spellbook@localhost",
                     "commit", "-m", "Temporary commit for validation", "--allow-empty"],
                    cwd=str(content_root),
                    capture_output=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                # Continuing here produced a raw GitPython traceback from every
                # pack in the run, naming nothing useful. The git stderr does
                # name the cause - typically one unreadable file, or a content
                # directory that is git-init-ed but has no commit, which is the
                # state spellbook's own init instructions leave between steps.
                detail = (e.stderr or b"").decode("utf-8", "replace").strip()
                first = detail.splitlines()[0] if detail else ""
                self._emit(ValidationIssue(
                    rule_name="sdk_git_setup_failed",
                    severity="error",
                    file_path=pack_name,
                    message=(
                        "could not prepare the temporary git repository "
                        "demisto-sdk requires" + (f": {first}" if first else "")
                    ),
                    consequence=(
                        "demisto-sdk cannot run without it, so the pack is "
                        "unvalidated; this is a failure rather than a skip"
                    ),
                    remediation=(
                        "the git error names the cause - typically one "
                        "unreadable file, or a content directory that is "
                        "git-init-ed but has no commit; fix that, or commit "
                        "the content, and re-run"
                    ),
                ), quiet)
                for line in detail.splitlines()[1:5]:
                    click.echo(f"        {line}", err=quiet)
                # This return is outside the try/finally that removes the
                # temporary repository. Left behind, a .git with no commit
                # makes every later run skip setup and crash the SDK - so
                # fixing the cause would no longer fix the pack.
                if git_initialised:
                    shutil.rmtree(git_dir, ignore_errors=True)
                self.last_failed_stages.append(STAGE_SDK)
                return False
        else:
            # A repository demisto-sdk cannot read HEAD from crashes it with
            # "Reference at 'refs/heads/main' does not exist" and no finding.
            # The commonest cause is a `git init` with no commit yet - the
            # state spellbook's own setup instructions pass through - so it is
            # named here, with its fix, rather than reported as an SDK fault.
            head_problem = self._unresolved_head(content_root)
            if head_problem is not None:
                self._emit(ValidationIssue(
                    rule_name="sdk_git_head_unresolved",
                    severity="error",
                    file_path=pack_name,
                    message=(
                        "the content repository has no commit git can resolve"
                        + (f": {head_problem}" if head_problem else "")
                    ),
                    consequence=(
                        "demisto-sdk reads the repository and crashes without "
                        "it, so the pack cannot be validated"
                    ),
                    remediation=(
                        "commit the content (git add -A && git commit -m "
                        "\"Initial commit\"); if the content directory is a git "
                        "worktree or submodule, its .git points outside the "
                        "mount, so mount the main repository instead. If it is "
                        "committed and `git log` works on the host, re-run: a "
                        "commit made an instant before can be unreadable "
                        "through a Docker Desktop mount"
                    ),
                ), quiet)
                self.last_failed_stages.append(STAGE_SDK)
                return False
        
        # The input path must be relative to the content root (the process
        # cwd). An absolute -i path makes demisto-sdk resolve its internal
        # CONTENT_PATH to an empty string, which later crashes validators
        # with "is not in the subpath of ''".
        cmd = [
            "demisto-sdk", "validate",
            "-i", str(pack_path.relative_to(content_root)),
            "-sv", ",".join(SDK_SELECTED_VALIDATIONS),
        ]

        skip_checks = validation_config.get("skip_checks", [])
        for check in skip_checks:
            cmd.extend(["--skip-pack-dependencies"])

        env = os.environ.copy()
        env["CONTENT_PATH"] = str(content_root)
        env["DEMISTO_SDK_CONTENT_PATH"] = str(content_root)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                cwd=str(content_root)
            )
            click.echo(result.stdout, nl=False, err=quiet)
            if result.stderr:
                click.echo(result.stderr, nl=False, err=True)

            output = f"{result.stdout or ''}\n{result.stderr or ''}"
            # The SDK already printed these; collected, not echoed again.
            self.last_stage_issues.extend(
                parse_sdk_findings(output, self.packs_dir.name)
            )
            crash = describe_sdk_failure(pack_name, result.returncode, output)
            if crash:
                self._emit(crash, quiet)

            # Part of this stage, not of the xsiam checks: see
            # SDK_DEFAULTS_CHECKED_NATIVELY. Run even when the SDK crashed,
            # since they need nothing from it.
            stand_in_errors = [
                issue
                for stand_in in SDK_DEFAULTS_CHECKED_NATIVELY.values()
                for issue in stand_in(pack_path)
                if issue.severity == "error"
            ]
            for issue in stand_in_errors:
                self._emit(issue, quiet)

            if result.returncode != 0 or stand_in_errors:
                self.last_failed_stages.append(STAGE_SDK)

            if result.returncode == 0 and not stand_in_errors:
                if not ruff_passed:
                    click.echo(f"Validation failed for {pack_name} (Python lint)", err=quiet)
                    return False
                if not tests_passed:
                    click.echo(f"Validation failed for {pack_name} (unit tests)", err=quiet)
                    return False
                click.echo(f"Validation passed for {pack_name}", err=quiet)
                self._check_gitkeep_files(pack_name)
                return True
            else:
                click.echo(f"Validation failed for {pack_name}", err=quiet)
                return False
        except FileNotFoundError:
            # Previously a [WARN] and a pass. A missing demisto-sdk is not a
            # clean pack: it is the validation gate absent, and returning the
            # lint/test result alone reported invalid content as valid. The
            # documented source install puts the console script wherever that
            # pip's bin directory is, so this is reachable by following the
            # README rather than by misconfiguration.
            self._emit(ValidationIssue(
                rule_name="sdk_not_found",
                severity="error",
                file_path=pack_name,
                message="demisto-sdk not found on PATH",
                consequence=(
                    "validation cannot run, so this is reported as a failure "
                    "rather than a pass - a missing gate is not a clean pack"
                ),
                remediation=(
                    "install it with pip install 'demisto-sdk==1.39.5', or use "
                    "the Docker image, which bundles it"
                ),
            ), quiet)
            self.last_failed_stages.append(STAGE_SDK)
            return False
        finally:
            if git_initialised:
                try:
                    shutil.rmtree(git_dir)
                except Exception:
                    pass

    @staticmethod
    def _unresolved_head(content_root: Path) -> str | None:
        """Return why HEAD does not resolve, or None when it does.

        None too when git itself is absent: that surfaces as its own failure
        further on, and is not this one. Retried briefly, because a commit made
        on the host just before a container starts can be unreadable through
        the mount for a moment (HEAD_RESOLVE_ATTEMPTS); waiting it out here
        also means demisto-sdk, which reads the same repository next, sees it
        settled.
        """
        for attempt in range(HEAD_RESOLVE_ATTEMPTS):
            if attempt:
                time.sleep(HEAD_RESOLVE_DELAY_SECONDS)
            try:
                result = subprocess.run(
                    ["git", "rev-parse", "--verify", "HEAD"],
                    cwd=str(content_root),
                    capture_output=True,
                    text=True,
                )
            except FileNotFoundError:
                return None
            if result.returncode == 0:
                return None
        return (result.stderr or "").strip().splitlines()[0] if result.stderr else ""

    def _emit(self, issue: ValidationIssue, quiet: bool) -> None:
        """Print a stage finding in the tagged shape and keep it for --json."""
        self.last_stage_issues.append(issue)
        click.echo("", err=quiet)
        for line in render_issue(issue, "ERROR"):
            click.echo(line, err=quiet)
        click.echo("", err=quiet)

    def _check_gitkeep_files(self, pack_name: str) -> None:
        """
        Check for .gitkeep files in the pack and warn if found.

        .gitkeep files are used during development to preserve empty
        directories in Git but must be removed before marketplace
        submission.

        Args:
            pack_name: Name of the pack to check.
        """
        pack_path = self.get_pack_path(pack_name)
        gitkeep_files = list(pack_path.rglob(".gitkeep"))
        
        if gitkeep_files:
            click.echo()
            for f in gitkeep_files:
                relative = f.relative_to(pack_path)
                click.echo(f"[WARN] {pack_name}: .gitkeep found at {relative} (remove empty folders before marketplace submission)")

    def package_pack(
        self,
        pack_name: str,
        output_dir: Path | None = None
    ) -> Path | None:
        """
        Package a pack into a zip file.

        Creates a zip archive containing all files and directories in the pack,
        matching the format expected by demisto-sdk upload.

        Args:
            pack_name: Name of the pack to package.
            output_dir: Directory for output zip file.

        Returns:
            Path to created zip file, or None if packaging failed.
        """
        packaging_config = self.config.get("packaging", {})
        if not packaging_config.get("create_zip", True):
            click.echo(f"Zip creation disabled, skipping {pack_name}")
            return None

        pack_path = self.get_pack_path(pack_name)
        if not pack_path.exists():
            click.echo(f"Pack not found: {pack_name}")
            return None

        if output_dir is None:
            output_dir = self.artifacts_dir

        if output_dir is None:
            click.echo(f"No output directory configured for {pack_name}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        metadata = self.read_pack_metadata(pack_name)
        version = metadata.get("currentVersion", "1.0.0")

        zip_name = f"{pack_name}-v{version}.zip"
        zip_path = output_dir / zip_name

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(pack_path, followlinks=False):
                    dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
                    for file in files:
                        file_path = os.path.join(root, file)
                        if os.path.islink(file_path):
                            click.echo(f"[WARN] Skipping symlink during packaging: {os.path.relpath(file_path, pack_path)}")
                            continue
                        arcname = os.path.relpath(file_path, pack_path)
                        zipf.write(file_path, arcname)

            click.echo(f"Created package: {zip_path}")
            return zip_path

        except Exception as e:
            click.echo(f"Failed to create package for {pack_name}: {e}")
            if zip_path.exists():
                zip_path.unlink()
            return None

    def build_pack(
        self,
        pack_name: str,
        validate: bool = True
    ) -> Path | None:
        """
        Build a complete pack (validate and package).

        Args:
            pack_name: Name of the pack to build.
            validate: Whether to run validation.

        Returns:
            Path to created zip file, or None if build failed.
        """
        click.echo(f"\n{'='*60}")
        click.echo(f"Building pack: {pack_name}")
        click.echo(f"{'='*60}")

        metadata = self.read_pack_metadata(pack_name)
        version = metadata.get("currentVersion", "1.0.0")
        click.echo(f"Version: {version}")

        if validate:
            if not self.validate_pack(pack_name):
                click.echo(f"Build failed for {pack_name}: validation errors")
                return None

        return self.package_pack(pack_name)

    def build_all_packs(
        self,
        validate: bool = True
    ) -> dict[str, Path | None]:
        """
        Build all discovered packs.

        Args:
            validate: Whether to run validation.

        Returns:
            Dictionary mapping pack names to their zip file paths.
        """
        packs = self.discover_packs()
        results = {}

        for pack_name in packs:
            results[pack_name] = self.build_pack(
                pack_name,
                validate=validate
            )

        return results

    def check_content_naming(self, pack_name: str) -> list[str]:
        """
        Check if content items have mismatched naming.

        Only CorrelationRules are checked. Modelling and parsing rules are
        conventionally named after their dataset, not the pack (this is the
        demisto/content convention and what `summon datamodel` produces), so
        flagging them against the pack name would be a false positive.

        Args:
            pack_name: Name of the pack to check.

        Returns:
            List of mismatched content item paths.
        """
        pack_path = self.get_pack_path(pack_name)
        if not pack_path.exists():
            return []

        mismatched = []
        content_types = ["CorrelationRules"]

        for content_type in content_types:
            content_dir = pack_path / content_type
            if not content_dir.exists():
                continue

            for item in content_dir.iterdir():
                if item.is_dir():
                    if not item.name.startswith(pack_name):
                        mismatched.append(str(item.relative_to(pack_path)))
                elif item.is_file() and item.suffix in [".yml", ".yaml"]:
                    if not item.stem.startswith(pack_name):
                        mismatched.append(str(item.relative_to(pack_path)))

        return mismatched

