#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
GoCortex Spellbook CLI

Command-line interface for building, validating, and packaging
Cortex Platform content packs.
"""

import os
import subprocess
import sys
from pathlib import Path

import click

from spellbook import __version__
from spellbook.pack_builder import PackBuilder
from spellbook.pack_template import PackTemplate
from spellbook.version_manager import VersionManager
from spellbook.instance import InstanceManager
from spellbook.xsiam_validator import XSIAMValidator
from spellbook.content_importer import CorrelationImporter


PINNED_SDK_VERSION = "1.38.18"


def get_version_info():
    """Get version information for spellbook, demisto-sdk, and Python."""
    import sys
    try:
        from importlib.metadata import version
        sdk_version = version("demisto-sdk")
    except Exception:
        sdk_version = "unknown"
    
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    
    return {
        "spellbook": __version__,
        "demisto_sdk": sdk_version,
        "python": python_version
    }


def check_environment(config_path: str, require_packs: bool = True) -> bool:
    """Check that required files and directories exist.
    
    Returns True if all checks pass, otherwise prints error and exits.
    """
    config_file = Path(config_path)
    
    if not config_file.exists():
        click.echo("")
        click.echo(f"[ERROR] Configuration file not found: {config_path}")
        click.echo("")
        click.echo("  This file is required to run Spellbook commands.")
        click.echo("")
        if config_path == "spellbook.yaml":
            click.echo("  When using Docker, ensure you mount the content directory:")
            click.echo("")
            click.echo("    docker run --rm -v $(pwd):/content \\")
            click.echo("      ghcr.io/gocortexio/spellbook <command>")
            click.echo("")
            click.echo("  Run this command from your content instance directory")
            click.echo("  (the folder containing spellbook.yaml and Packs/).")
        else:
            click.echo(f"  Check that the path '{config_path}' is correct.")
        click.echo("")
        sys.exit(1)
    
    if require_packs:
        builder = PackBuilder(config_path)
        if not builder.check_packs_dir_exists():
            click.echo("")
            click.echo(f"[ERROR] Packs directory not found: {builder.packs_dir}")
            click.echo("")
            click.echo("  The Packs/ directory is required for this command.")
            click.echo("")
            click.echo("  When using Docker, ensure you mount the content directory:")
            click.echo("")
            click.echo("    docker run --rm -v $(pwd):/content \\")
            click.echo("      ghcr.io/gocortexio/spellbook <command>")
            click.echo("")
            click.echo("  Run this command from your content instance directory.")
            click.echo("")
            sys.exit(1)
    
    return True


def validate_version_format(version: str) -> bool:
    """Check if version matches X.Y.Z format."""
    import re
    pattern = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
    return pattern.match(version) is not None


def normalise_version(version: str) -> str:
    """Strip 'v' prefix if present and return clean version string."""
    if version.startswith("v") or version.startswith("V"):
        return version[1:]
    return version


def check_git_repository(command_name: str = "bump-version") -> bool:
    """
    Check if the current directory is within a Git repository.
    
    Args:
        command_name: Name of command for error messages.
    
    Returns:
        True if in a Git repository, exits with error otherwise.
    """
    try:
        git_check = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True
        )
        if git_check.returncode != 0:
            click.echo("")
            click.echo("[ERROR] Git repository not initialised")
            click.echo("")
            click.echo("  The --tag flag requires a Git repository to create commits and tags.")
            click.echo("")
            click.echo("  To initialise Git in your content directory:")
            click.echo("")
            click.echo("    git init")
            click.echo("    git add .")
            click.echo("    git commit -m \"Initial commit\"")
            click.echo("")
            sys.exit(1)
        return True
    except FileNotFoundError:
        click.echo("[ERROR] Git not found")
        click.echo("")
        click.echo("  The --tag flag requires Git to be installed.")
        click.echo("")
        sys.exit(1)


def create_pack_tag(pack_name: str, version: str, pack_path: Path, command_name: str = "bump-version", message: str | None = None) -> bool:
    """
    Stage all files in pack directory, commit, and create a Git tag.
    
    Args:
        pack_name: Name of the pack.
        version: Version string (without 'v' prefix).
        pack_path: Path to the pack directory.
        command_name: Name of command for error messages.
        message: Optional custom commit message. If not provided, uses default format.
    
    Returns:
        True if successful, False otherwise.
    """
    try:
        git_user_name = subprocess.run(
            ["git", "config", "--get", "user.name"],
            capture_output=True, text=True
        )
        git_user_email = subprocess.run(
            ["git", "config", "--get", "user.email"],
            capture_output=True, text=True
        )
    except FileNotFoundError:
        click.echo("[WARN] Git not found, skipping tag creation")
        return False
    
    if not git_user_name.stdout.strip() or not git_user_email.stdout.strip():
        click.echo("")
        click.echo("[ERROR] Git identity not configured")
        click.echo("")
        click.echo("  The --tag flag requires git user.name and user.email to be set.")
        click.echo("")
        click.echo("  Configuration           Status")
        click.echo("  ---------------------   ------")
        name_status = "[OK] set" if git_user_name.stdout.strip() else "[MISSING]"
        email_status = "[OK] set" if git_user_email.stdout.strip() else "[MISSING]"
        click.echo(f"  user.name               {name_status}")
        click.echo(f"  user.email              {email_status}")
        click.echo("")
        click.echo("When using Docker, mount your git config:")
        click.echo("")
        click.echo("  docker run --rm \\")
        click.echo("    -v $(pwd):/content \\")
        click.echo("    -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \\")
        click.echo(f"    ghcr.io/gocortexio/spellbook {command_name} {pack_name} --tag")
        click.echo("")
        sys.exit(1)
    
    tag_name = f"{pack_name}-v{version}"
    try:
        subprocess.run(
            ["git", "add", str(pack_path)],
            capture_output=True,
            text=True,
            check=True
        )
        commit_message = message if message else f"{pack_name} v{version}"
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            capture_output=True,
            text=True,
            check=True
        )
        click.echo(f"[OK] Committed: {commit_message}")
        subprocess.run(
            ["git", "tag", tag_name],
            capture_output=True,
            text=True,
            check=True
        )
        click.echo(f"[OK] Created Git tag: {tag_name}")
        click.echo(f"     Push with: git push && git push origin {tag_name}")
        return True
    except subprocess.CalledProcessError as e:
        click.echo(f"[WARN] Failed to create Git tag: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        click.echo("[WARN] Git not found, skipping tag creation")
        return False


BANNER = r"""
                             /\
                            /  \
                           |    |
                         --:'''':--
                           :'_' :
                           _:"":\___
                     ____.' :::     '._
                *=====<<=)           \    :
                 '      '-'-'\_      /'._.'
                             \====:_ ""
                            .'     \\
                           :       :
                          /   :    \
                         :   .      '.
      _____              :  : :      :            _
     / ____|             :__:-:__.;--'           | |
    | (___  _ __   ___   '-'   '-'    ___   ___ | | __
     \___ \| '_ \ / _ \  ,. _        / _ \ / _ \| |/ /
     ____) | |_) |  __/'-'    ).    | (_) | (_) |   <
    |_____/| .__/ \___| (     '  )   \___/ \___/|_|\_\
           | |      ( -  .00.  - _
           |_|     (   .'  _ )    )
                   '- ()_.\,\,  -
"""


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="Spellbook")
@click.pass_context
def cli(ctx):
    """Spellbook - Cortex Platform Content Pack Builder

    A tool for building, validating, and packaging Cortex Platform
    content packs.
    """
    if ctx.invoked_subcommand is None:
        versions = get_version_info()
        click.echo(BANNER)
        click.echo("  GoCortex Spellbook")
        click.echo("  Cortex Platform Content Pack Builder")
        click.echo("")
        click.echo(f"  spellbook-version: {versions['spellbook']}")
        click.echo(f"  demisto-sdk-version: {versions['demisto_sdk']} (PINNED)")
        click.echo(f"  python-version: {versions['python']}")
        click.echo("")
        click.echo("  Run 'spellbook.py --help' for available commands.")
        click.echo("")


@cli.command()
@click.argument("instance_name")
@click.option(
    "--author",
    "-a",
    default="",
    help="Default author for packs in this instance."
)
@click.option(
    "--description",
    "-d",
    default="",
    help="Description of the instance."
)
@click.option(
    "--no-ci",
    is_flag=True,
    default=False,
    help="Skip creating GitHub Actions workflows."
)
def init(instance_name, author, description, no_ci):
    """Initialise a new content instance.

    Creates a new folder with its own Git structure, GitHub Actions,
    and starter pack. The instance is independent from Spellbook
    and can be pushed to your own repository.
    """
    click.echo(f"Spellbook v{__version__}")
    click.echo("")
    manager = InstanceManager()
    try:
        instance_path = manager.create_instance(
            instance_name,
            author=author,
            description=description,
            include_ci=not no_ci
        )
        click.echo(f"[OK] Created instance: {instance_path}")
        click.echo("")
        click.echo("Next steps:")
        click.echo(f"  1. cd {instance_name}")
        click.echo("  2. git init")
        click.echo("  3. git branch -M main")
        click.echo("  4. git add .")
        click.echo('  5. git commit -s -m "Initial commit"')
        click.echo("")
        click.echo("Optional (if using a remote repository):")
        click.echo("  6. git remote add origin <your-repo-url>")
        click.echo("  7. git push -u origin main")
        click.echo("")
        click.echo("Then start developing your packs in Packs/")
        click.echo("")
        click.echo("To build packs (creates zip in artifacts/):")
        click.echo("  docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook:latest build --all")
    except FileExistsError as e:
        click.echo(f"[ERROR] {e}")
        sys.exit(1)


@cli.command()
def list_instances():
    """List all content instances."""
    manager = InstanceManager()
    instances = manager.list_instances()

    if not instances:
        click.echo("No instances found.")
        click.echo("Create one with: docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook:latest init <name>")
        return

    click.echo(f"Found {len(instances)} instance(s):\n")
    for ws in instances:
        click.echo(f"  - {ws}/")


@cli.command()
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def list_packs(config):
    """List all discovered content packs."""
    click.echo(f"Spellbook v{__version__}")
    click.echo("")
    builder = PackBuilder(config)
    packs = builder.discover_packs()

    if not packs:
        click.echo("No packs found.")
        return

    click.echo(f"Found {len(packs)} pack(s):\n")
    for pack in packs:
        metadata = builder.read_pack_metadata(pack)
        version = metadata.get("currentVersion", "unknown")
        description = metadata.get("description", "")[:50]
        click.echo(f"  - {pack} (v{version})")
        if description:
            click.echo(f"    {description}...")


@cli.command()
@click.argument("pack_name", required=False)
@click.option(
    "--all",
    "-a",
    "build_all",
    is_flag=True,
    help="Build all discovered packs."
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Run validation before packaging."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def build(pack_name, build_all, validate, config):
    """Build and package content packs.

    Specify a PACK_NAME to build a single pack, or use --all to build
    all discovered packs. The version is read from pack_metadata.json.
    """
    click.echo(f"Spellbook v{__version__}")
    builder = PackBuilder(config)

    if build_all:
        results = builder.build_all_packs(validate=validate)
        success = sum(1 for r in results.values() if r is not None)
        failed = len(results) - success
        click.echo(f"\nBuild complete: {success} succeeded, {failed} failed")
    elif pack_name:
        builder.validate_pack_exists(pack_name)
        result = builder.build_pack(pack_name, validate=validate)
        if result:
            click.echo(f"\nBuild successful: {result}")
        else:
            click.echo("\nBuild failed")
            sys.exit(1)
    else:
        click.echo("Please specify a pack name or use --all")
        sys.exit(1)


@cli.command()
@click.argument("pack_name")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def validate(pack_name, config):
    """Validate a content pack using demisto-sdk and XSIAM checks."""
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    
    sdk_passed = builder.validate_pack(pack_name)
    
    xsiam_validator = XSIAMValidator(builder.packs_dir)
    xsiam_issues = xsiam_validator.validate_pack(pack_name)
    xsiam_errors = [i for i in xsiam_issues if i.severity == "error"]
    
    if xsiam_issues:
        click.echo("")
        click.echo(xsiam_validator.format_issues(xsiam_issues))
        click.echo("")
    
    if sdk_passed and not xsiam_errors:
        click.echo("[PASS] Validation passed")
    else:
        click.echo("[FAIL] Validation failed")
        sys.exit(1)


@cli.command("validate-all")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def validate_all(config):
    """Validate all discovered content packs using demisto-sdk and XSIAM checks."""
    builder = PackBuilder(config)
    packs = builder.discover_packs()

    if not packs:
        click.echo("No packs found.")
        return

    xsiam_validator = XSIAMValidator(builder.packs_dir)
    failed = []
    
    for pack in packs:
        click.echo(f"Validating {pack}...")
        sdk_passed = builder.validate_pack(pack)
        
        xsiam_issues = xsiam_validator.validate_pack(pack)
        xsiam_errors = [i for i in xsiam_issues if i.severity == "error"]
        
        if xsiam_issues:
            click.echo(xsiam_validator.format_issues(xsiam_issues))
        
        if not sdk_passed or xsiam_errors:
            failed.append(pack)

    if failed:
        click.echo(f"\n[FAIL] Validation failed for: {', '.join(failed)}")
        sys.exit(1)
    else:
        click.echo(f"\n[PASS] All {len(packs)} packs validated")




@cli.command()
@click.argument("pack_name")
@click.option(
    "--description",
    "-d",
    default="",
    help="Pack description."
)
@click.option(
    "--author",
    "-a",
    default=None,
    help="Pack author."
)
@click.option(
    "--template",
    "-t",
    default="default",
    type=click.Choice(["default", "integration", "playbook", "minimal"]),
    help="Template to use for pack creation."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def create(pack_name, description, author, template, config):
    """Create a new content pack from template."""
    template_gen = PackTemplate(config)
    pack_path = template_gen.create_from_template(
        template,
        pack_name,
        description
    )
    click.echo(f"[OK] Created pack at: {pack_path}")


@cli.command()
@click.argument("pack_name")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def version(pack_name, config):
    """Show version information for a pack."""
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    vm = VersionManager()

    metadata = builder.read_pack_metadata(pack_name)
    current = metadata.get("currentVersion", "unknown")

    click.echo(f"Pack: {pack_name}")
    click.echo(f"  Version:    {current}")

    if vm.is_git_repository():
        latest_tag_version = vm.get_latest_version(pack_name)
        if latest_tag_version != vm.DEFAULT_VERSION or vm.get_git_tags():
            latest_tag = f"{pack_name}-v{latest_tag_version}"
            click.echo(f"  Latest tag: {latest_tag}")
        else:
            click.echo("  Latest tag: (none)")


@cli.command()
@click.argument("pack_name")
@click.argument("new_version")
@click.option(
    "--tag",
    "-t",
    is_flag=True,
    default=False,
    help="Create a Git tag for the new version."
)
@click.option(
    "--message",
    "-m",
    default=None,
    help="Custom commit message (requires --tag)."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def set_version(pack_name, new_version, tag, message, config):
    """Set the version for a pack.
    
    Accepts version with or without 'v' prefix (e.g., 2.0.0 or v2.0.0).
    Use --tag to stage all pack files, commit, and create a Git tag.
    """
    clean_version = normalise_version(new_version)
    
    if not validate_version_format(clean_version):
        click.echo(f"[ERROR] Invalid version format: {new_version}")
        click.echo("")
        click.echo("  Version must match format X.Y.Z where X, Y, Z are integers.")
        click.echo("")
        click.echo("  Examples:")
        click.echo("    gocortex-spellbook set-version MyPack 2.0.0")
        click.echo("    gocortex-spellbook set-version MyPack v2.0.0")
        click.echo("")
        sys.exit(1)
    
    if message and not tag:
        click.echo("[ERROR] --message requires --tag")
        click.echo("")
        click.echo("  The --message flag is only valid when creating a Git commit.")
        click.echo("")
        click.echo("  Usage:")
        click.echo("    gocortex-spellbook set-version MyPack 2.0.0 --tag --message \"Your message\"")
        click.echo("")
        sys.exit(1)
    
    if tag:
        check_git_repository("set-version")
    
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    builder.update_pack_version(pack_name, clean_version)
    click.echo(f"[OK] Set {pack_name} version to {clean_version}")
    
    if tag:
        pack_path = builder.packs_dir / pack_name
        create_pack_tag(pack_name, clean_version, pack_path, "set-version", message)


@cli.command("bump-version")
@click.argument("pack_name")
@click.option(
    "--major",
    is_flag=True,
    default=False,
    help="Increment major version (x.0.0)."
)
@click.option(
    "--minor",
    is_flag=True,
    default=False,
    help="Increment minor version (0.x.0)."
)
@click.option(
    "--revision",
    is_flag=True,
    default=True,
    help="Increment revision version (0.0.x). Default."
)
@click.option(
    "--tag",
    "-t",
    is_flag=True,
    default=False,
    help="Create a Git tag for the new version."
)
@click.option(
    "--message",
    "-m",
    default=None,
    help="Custom commit message (requires --tag)."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def bump_version(pack_name, major, minor, revision, tag, message, config):
    """Automatically increment a pack version.

    Reads the current version from pack_metadata.json, increments it,
    and writes the new version back. Also creates a ReleaseNotes file
    for the new version.

    Use --tag to also create a Git tag for the new version.
    """
    if message and not tag:
        click.echo("[ERROR] --message requires --tag")
        click.echo("")
        click.echo("  The --message flag is only valid when creating a Git commit.")
        click.echo("")
        click.echo("  Usage:")
        click.echo("    gocortex-spellbook bump-version MyPack --tag --message \"Your message\"")
        click.echo("")
        sys.exit(1)
    
    if tag:
        check_git_repository("bump-version")
    
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)

    if major:
        increment_type = "major"
    elif minor:
        increment_type = "minor"
    else:
        increment_type = "revision"

    metadata = builder.read_pack_metadata(pack_name)
    metadata_version = metadata.get("currentVersion", "1.0.0")

    if tag:
        tag_version = builder.version_manager.get_latest_version(pack_name)
        has_pack_tags = any(
            builder.version_manager.parse_tag(t, pack_name)
            for t in builder.version_manager.get_git_tags()
        )
        if has_pack_tags:
            current_version = max(
                [metadata_version, tag_version],
                key=lambda v: builder.version_manager._version_tuple(v)
            )
        else:
            current_version = metadata_version
    else:
        current_version = metadata_version

    new_version = builder.version_manager.increment_version(
        current_version, increment_type
    )

    builder.update_pack_version(pack_name, new_version)
    click.echo(f"[OK] Bumped {pack_name} from {current_version} to {new_version}")

    pack_path = builder.packs_dir / pack_name
    release_notes_dir = pack_path / "ReleaseNotes"
    release_notes_dir.mkdir(exist_ok=True)
    
    version_filename = new_version.replace(".", "_") + ".md"
    release_notes_path = release_notes_dir / version_filename
    
    if not release_notes_path.exists():
        release_content = f"""#### Parsing Rules

##### {pack_name} Parsing Rule

- (Describe parsing rule changes here)

#### Modeling Rules

##### {pack_name} Modeling Rule

- (Describe modelling rule changes here)

#### Correlation Rules

##### {pack_name} - (Rule Name)

- (Describe correlation rule changes here)
"""
        with open(release_notes_path, "w", encoding="utf-8") as f:
            f.write(release_content)
        click.echo(f"[OK] Created release notes: ReleaseNotes/{version_filename}")
        click.echo("")
        click.echo("[INFO] Remember to update the release notes with your changes:")
        click.echo(f"       {release_notes_path}")

    if tag:
        create_pack_tag(pack_name, new_version, pack_path, "bump-version", message)


@cli.command("rename-content")
@click.argument("pack_name")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def rename_content(pack_name, config):
    """Rename all content items to match the pack name.

    Use this after copying content from another pack to fix naming
    mismatches. This command renames folders, files, and internal
    IDs in ModelingRules, ParsingRules, and CorrelationRules.
    """
    click.echo("[INFO] The rename-content command is temporarily unavailable.")
    click.echo("")
    click.echo("This command is being improved to handle additional edge cases.")
    click.echo("For now, please rename content items manually.")
    sys.exit(0)

    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)

    mismatched = builder.check_content_naming(pack_name)
    if not mismatched:
        click.echo(f"[OK] All content items in {pack_name} already match the pack name")
        return

    click.echo(f"Found {len(mismatched)} mismatched content item(s):")
    for item in mismatched:
        click.echo(f"  - {item}")
    click.echo("")

    try:
        renamed = builder.rename_content(pack_name)
        if renamed:
            click.echo(f"[OK] Renamed {len(renamed)} item(s):")
            for old, new in renamed.items():
                click.echo(f"  {old} -> {new}")
            click.echo("")
            click.echo("Content has been updated. You should now rebuild the pack:")
            click.echo(f"  gocortex-spellbook build {pack_name}")
        else:
            click.echo("[OK] No items needed renaming")
    except FileNotFoundError as e:
        click.echo(f"[ERROR] {e}")
        sys.exit(1)


@cli.command()
@click.argument("pack_path")
@click.option(
    "--xsiam",
    "-x",
    is_flag=True,
    default=False,
    help="Upload to XSIAM server."
)
@click.option(
    "--insecure",
    is_flag=True,
    default=False,
    help="Skip certificate validation."
)
@click.option(
    "--skip-validation",
    is_flag=True,
    default=False,
    help="Skip pack validation before upload."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def upload(pack_path, xsiam, insecure, skip_validation, config):
    """Upload a content pack to Cortex Platform.

    PACK_PATH must be a pack directory (e.g., Packs/MyPack).

    Required environment variables:
      DEMISTO_BASE_URL - Your instance URL
      DEMISTO_API_KEY  - API key with Instance Administrator role

    For XSIAM, also set:
      XSIAM_AUTH_ID    - Authentication ID from your instance
    """
    base_url = os.environ.get("DEMISTO_BASE_URL")
    api_key = os.environ.get("DEMISTO_API_KEY")
    xsiam_auth_id = os.environ.get("XSIAM_AUTH_ID")

    env_vars = [
        ("DEMISTO_BASE_URL", base_url, True),
        ("DEMISTO_API_KEY", api_key, True),
        ("XSIAM_AUTH_ID", xsiam_auth_id, xsiam),
    ]
    
    missing = []
    for name, value, required in env_vars:
        if required and not value:
            missing.append(name)
    
    if missing:
        click.echo("")
        click.echo("[ERROR] Missing required environment variables for upload")
        click.echo("")
        click.echo("  Variable           Status")
        click.echo("  ----------------   ------")
        for name, value, required in env_vars:
            if not required:
                continue
            status = "[OK] set" if value else "[MISSING]"
            suffix = " (required with --xsiam)" if name == "XSIAM_AUTH_ID" else ""
            click.echo(f"  {name:<18} {status}{suffix}")
        click.echo("")
        click.echo("Example Docker command:")
        click.echo("")
        if xsiam:
            click.echo('  docker run --rm -v $(pwd):/content \\')
            click.echo('    -e DEMISTO_BASE_URL="https://your-instance.xdr.paloaltonetworks.com" \\')
            click.echo('    -e DEMISTO_API_KEY="your-api-key" \\')
            click.echo('    -e XSIAM_AUTH_ID="your-auth-id" \\')
            click.echo('    ghcr.io/gocortexio/spellbook upload Packs/MyPack --xsiam')
        else:
            click.echo('  docker run --rm -v $(pwd):/content \\')
            click.echo('    -e DEMISTO_BASE_URL="https://your-instance.demisto.com" \\')
            click.echo('    -e DEMISTO_API_KEY="your-api-key" \\')
            click.echo('    ghcr.io/gocortexio/spellbook upload Packs/MyPack')
        click.echo("")
        click.echo("Or use an env file:")
        click.echo("")
        click.echo("  docker run --rm -v $(pwd):/content --env-file .env \\")
        click.echo("    ghcr.io/gocortexio/spellbook upload Packs/MyPack")
        click.echo("")
        sys.exit(1)

    input_file = Path(pack_path)
    if not input_file.exists():
        click.echo(f"[ERROR] Path not found: {pack_path}")
        sys.exit(1)

    if not input_file.is_dir():
        click.echo(f"[ERROR] Pack path must be a directory: {pack_path}")
        click.echo("")
        click.echo("Usage: upload Packs/MyPack --xsiam")
        click.echo("")
        click.echo("Note: Upload from pre-built zip files is not supported.")
        click.echo("Always upload from the pack directory.")
        sys.exit(1)

    pack_name = input_file.name
    builder = PackBuilder(config)
    mismatched = builder.check_content_naming(pack_name)
    if mismatched:
        click.echo(f"[WARN] Content naming mismatch: {pack_name} has items with different names")
        for item in mismatched[:5]:
            click.echo(f"  - {item}")
        if len(mismatched) > 5:
            click.echo(f"  ... and {len(mismatched) - 5} more")
        click.echo("")
        click.echo("This may cause upload to fail. To fix, run:")
        click.echo(f"  gocortex-spellbook rename-content {pack_name}")
        click.echo(f"  gocortex-spellbook build {pack_name}")
        click.echo("")

    content_root = input_file.parent.parent.resolve()
    git_dir = content_root / ".git"
    git_initialised = False
    
    if not git_dir.exists():
        click.echo("Setting up temporary git repository for upload...")
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
                 "commit", "-m", "Temporary commit for upload", "--allow-empty"],
                cwd=str(content_root),
                capture_output=True,
                check=True
            )
        except subprocess.CalledProcessError as e:
            click.echo(f"[WARN] Could not initialise git repository: {e}")

    cmd = ["demisto-sdk", "upload", "-i", str(input_file), "-z"]

    if xsiam:
        cmd.append("--xsiam")

    if insecure:
        cmd.append("--insecure")

    if skip_validation:
        cmd.append("--skip-validation")

    click.echo(f"Uploading {pack_path}...")
    click.echo(f"Target: {base_url}")

    try:
        env = os.environ.copy()
        env["CONTENT_PATH"] = str(content_root)
        env["DEMISTO_SDK_CONTENT_PATH"] = str(content_root)
        
        result = subprocess.run(cmd, check=False, env=env, cwd=str(content_root))
        if result.returncode == 0:
            click.echo("[OK] Upload completed")
        else:
            click.echo("[FAIL] Upload failed")
            sys.exit(result.returncode)
    except FileNotFoundError:
        click.echo("[ERROR] demisto-sdk not found")
        click.echo("Install it with: pip install demisto-sdk")
        sys.exit(1)
    finally:
        if git_initialised:
            try:
                import shutil
                shutil.rmtree(git_dir)
            except Exception:
                pass


@cli.command(name="check-init")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def check_init(config):
    """Check the initialised instance environment.
    
    Validates that the current content instance is properly configured
    and ready for use. Run this command to troubleshoot issues before
    running other commands.
    """
    versions = get_version_info()
    click.echo("")
    click.echo("Spellbook Check-Init")
    click.echo("====================")
    click.echo("")
    
    click.echo("Version Information")
    click.echo("-------------------")
    click.echo(f"  spellbook-version: {versions['spellbook']}")
    click.echo(f"  demisto-sdk-version: {versions['demisto_sdk']}")
    click.echo(f"  python-version: {versions['python']}")
    click.echo("")
    
    all_ok = True
    has_warnings = False
    
    click.echo("Environment Checks")
    click.echo("------------------")
    
    config_file = Path(config)
    if config_file.exists():
        click.echo(f"[OK] Configuration file: {config}")
    else:
        click.echo(f"[FAIL] Configuration file: {config} (not found)")
        all_ok = False
    
    if config_file.exists():
        builder = PackBuilder(config)
        if builder.check_packs_dir_exists():
            packs = builder.discover_packs()
            click.echo(f"[OK] Packs directory: {builder.packs_dir} ({len(packs)} pack(s))")
        else:
            click.echo(f"[FAIL] Packs directory: {builder.packs_dir} (not found)")
            all_ok = False
        
        if builder.artifacts_dir.exists():
            click.echo(f"[OK] Artifacts directory: {builder.artifacts_dir}")
        else:
            click.echo(f"[INFO] Artifacts directory: {builder.artifacts_dir} (will be created)")
    
    try:
        git_check = subprocess.run(["git", "--version"], capture_output=True, text=True)
        if git_check.returncode == 0:
            click.echo(f"[OK] Git: {git_check.stdout.strip()}")
        else:
            click.echo("[FAIL] Git: not found")
            all_ok = False
    except FileNotFoundError:
        click.echo("[FAIL] Git: not found")
        all_ok = False
        git_check = None
    
    if git_check and git_check.returncode == 0:
        try:
            git_user_name = subprocess.run(
                ["git", "config", "--get", "user.name"],
                capture_output=True, text=True
            )
            git_user_email = subprocess.run(
                ["git", "config", "--get", "user.email"],
                capture_output=True, text=True
            )
            
            if git_user_name.stdout.strip():
                click.echo(f"[OK] Git user.name: {git_user_name.stdout.strip()}")
            else:
                click.echo("[WARN] Git user.name: not set (required for --tag)")
                has_warnings = True
                
            if git_user_email.stdout.strip():
                click.echo(f"[OK] Git user.email: {git_user_email.stdout.strip()}")
            else:
                click.echo("[WARN] Git user.email: not set (required for --tag)")
                has_warnings = True
        except FileNotFoundError:
            pass
    
    try:
        sdk_check = subprocess.run(
            ["demisto-sdk", "--version"],
            capture_output=True, text=True
        )
        if sdk_check.returncode == 0:
            click.echo(f"[OK] demisto-sdk: available")
        else:
            click.echo("[FAIL] demisto-sdk: not found")
            all_ok = False
    except FileNotFoundError:
        click.echo("[FAIL] demisto-sdk: not found")
        all_ok = False
    
    click.echo("")
    click.echo("Upload Environment Variables")
    click.echo("----------------------------")
    
    base_url = os.environ.get("DEMISTO_BASE_URL")
    api_key = os.environ.get("DEMISTO_API_KEY")
    xsiam_auth_id = os.environ.get("XSIAM_AUTH_ID")
    
    if base_url:
        click.echo(f"[OK] DEMISTO_BASE_URL: {base_url[:30]}...")
    else:
        click.echo("[INFO] DEMISTO_BASE_URL: not set (required for upload)")
    
    if api_key:
        click.echo("[OK] DEMISTO_API_KEY: set (hidden)")
    else:
        click.echo("[INFO] DEMISTO_API_KEY: not set (required for upload)")
    
    if xsiam_auth_id:
        click.echo("[OK] XSIAM_AUTH_ID: set (hidden)")
    else:
        click.echo("[INFO] XSIAM_AUTH_ID: not set (required for XSIAM upload)")
    
    upload_ready = base_url and api_key
    
    click.echo("")
    if not all_ok:
        click.echo("[FAIL] Some checks failed - see above for details")
    elif has_warnings:
        click.echo("[WARN] Ready for builds, but some items need attention")
    elif not upload_ready:
        click.echo("[INFO] Ready for local builds. Upload requires environment variables.")
    else:
        click.echo("[OK] All checks passed")
    click.echo("")


@cli.group()
def summon():
    """Import content from Cortex Platform exports.

    Summon commands import content that has been exported from the
    Cortex Platform and convert it to pack-ready YAML files.

    \b
    Usage:
        cat export.json | spellbook summon correlation MyPack
        spellbook summon correlation MyPack < export.json

    \b
    For Docker:
        cat export.json | docker run -i --rm -v $(pwd):/content \\
            ghcr.io/gocortexio/spellbook summon correlation MyPack
    """
    pass


@summon.command("correlation")
@click.argument("pack_name")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def summon_correlation(pack_name, config):
    """Import correlation rules from JSON export.

    Reads a JSON array of correlation rules from stdin (piped input or
    interactive paste followed by Ctrl+D) and creates YAML files in the
    pack's CorrelationRules directory.

    The JSON must be an array (even for single rules). Each rule is
    cleaned of platform-specific fields, assigned a new UUID, and
    converted to YAML format.

    Example:
      cat rules.json | spellbook summon correlation MyPack
      spellbook summon correlation MyPack < rules.json
    """
    check_environment(config)
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)

    click.echo(f"Spellbook v{__version__}")
    click.echo("")
    click.echo(f"Summoning correlation rules into {pack_name}...")
    click.echo("Reading from stdin (paste JSON, then Ctrl+D to finish)")
    click.echo("")

    try:
        json_content = sys.stdin.read()
    except KeyboardInterrupt:
        click.echo("")
        click.echo("[INFO] Cancelled")
        sys.exit(0)

    if not json_content.strip():
        click.echo("[ERROR] No input received")
        click.echo("")
        click.echo("  Pipe JSON content or paste and press Ctrl+D:")
        click.echo("    cat rules.json | spellbook summon correlation MyPack")
        click.echo("")
        sys.exit(1)

    importer = CorrelationImporter(builder.packs_dir)

    try:
        results = importer.import_from_json(json_content, pack_name)
    except ValueError as e:
        click.echo(f"[ERROR] {e}")
        sys.exit(1)

    success_count = 0
    for result in results:
        if result["success"]:
            for warning in result.get("warnings", []):
                click.echo(f"[WARN] {result['name']}: {warning}")
            if result.get("overwritten"):
                click.echo(f"[WARN] {result['name']}: overwrote {result['filename']}")
            else:
                click.echo(f"[OK] {result['name']}: created {result['filename']}")
            success_count += 1
        else:
            click.echo(f"[ERROR] {result['name']}: {result['error']}")

    click.echo("")
    if success_count == len(results):
        click.echo(f"[OK] Summoned {success_count} correlation rule(s) to {pack_name}")
    else:
        failed = len(results) - success_count
        click.echo(f"[WARN] Summoned {success_count} rule(s), {failed} failed")
        sys.exit(1)


if __name__ == "__main__":
    cli()
