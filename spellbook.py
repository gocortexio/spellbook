#!/usr/bin/env python3
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


BANNER = r"""
    *    .        *         .        *        .    *          /\
        .    *        .         *         .                  /  \
   .        *    .        *    .    *         .    *        /____\
       _____            _ _ _                 _          <   (O O)   >
      / ____|          | | | |               | |             ####
     | (___  _ __   ___| | | |__   ___   ___ | | __          \~~~/
  *   \___ \| '_ \ / _ \ | | '_ \ / _ \ / _ \| |/ /   *     _/ || \_
      ____) | |_) |  __/ | | |_) | (_) | (_) |   <        /{      }\
     |_____/| .__/ \___|_|_|_.__/ \___/ \___/|_|\_\      ( {{    }} )
            | |                                          \_/    \_/
    .    *  |_|  .    *         .         *    .
        *        .    *    .        *   .        *
   *        .         *        .            *      .
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
        click.echo(BANNER)
        click.echo(f"  GoCortex Spellbook v{__version__}")
        click.echo("  Cortex Platform Content Pack Builder")
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
        click.echo(f"  docker run --rm -v $(pwd):/content gocortex-spellbook build --all")
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
        click.echo("Create one with: docker run --rm -v $(pwd):/content gocortex-spellbook init <name>")
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
    "--lint/--no-lint",
    default=False,
    help="Run linting before packaging."
)
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def build(pack_name, build_all, validate, lint, config):
    """Build and package content packs.

    Specify a PACK_NAME to build a single pack, or use --all to build
    all discovered packs. The version is read from pack_metadata.json.
    """
    click.echo(f"Spellbook v{__version__}")
    builder = PackBuilder(config)

    if build_all:
        results = builder.build_all_packs(
            validate=validate,
            lint=lint
        )
        success = sum(1 for r in results.values() if r is not None)
        failed = len(results) - success
        click.echo(f"\nBuild complete: {success} succeeded, {failed} failed")
    elif pack_name:
        builder.validate_pack_exists(pack_name)
        result = builder.build_pack(
            pack_name,
            validate=validate,
            lint=lint
        )
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
    """Validate a content pack using demisto-sdk."""
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    if builder.validate_pack(pack_name):
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
    """Validate all discovered content packs."""
    builder = PackBuilder(config)
    packs = builder.discover_packs()

    if not packs:
        click.echo("No packs found.")
        return

    failed = []
    for pack in packs:
        click.echo(f"Validating {pack}...")
        if not builder.validate_pack(pack):
            failed.append(pack)

    if failed:
        click.echo(f"\n[FAIL] Validation failed for: {', '.join(failed)}")
        sys.exit(1)
    else:
        click.echo(f"\n[PASS] All {len(packs)} packs validated successfully")


@cli.command()
@click.argument("pack_name")
@click.option(
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def lint(pack_name, config):
    """Lint a content pack using demisto-sdk pre-commit."""
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    if builder.lint_pack(pack_name):
        click.echo("[PASS] Linting passed")
    else:
        click.echo("[FAIL] Linting failed")
        sys.exit(1)


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
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def set_version(pack_name, new_version, config):
    """Set the version for a pack."""
    builder = PackBuilder(config)
    builder.validate_pack_exists(pack_name)
    builder.update_pack_version(pack_name, new_version)
    click.echo(f"[OK] Set {pack_name} version to {new_version}")


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
    "--config",
    "-c",
    default="spellbook.yaml",
    help="Path to configuration file."
)
def bump_version(pack_name, major, minor, revision, tag, config):
    """Automatically increment a pack version.

    Reads the current version from pack_metadata.json, increments it,
    and writes the new version back. Also creates a ReleaseNotes file
    for the new version.

    Use --tag to also create a Git tag for the new version.
    """
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
        tag_name = f"{pack_name}-v{new_version}"
        try:
            result = subprocess.run(
                ["git", "tag", tag_name],
                capture_output=True,
                text=True,
                check=True
            )
            click.echo(f"[OK] Created Git tag: {tag_name}")
            click.echo(f"     Push with: git push origin {tag_name}")
        except subprocess.CalledProcessError as e:
            click.echo(f"[WARN] Failed to create Git tag: {e.stderr.strip()}")
        except FileNotFoundError:
            click.echo("[WARN] Git not found, skipping tag creation")


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
@click.argument("input_path")
@click.option(
    "--zip/--no-zip",
    "-z/-nz",
    default=False,
    help="Compress pack to zip before upload (for pack directories)."
)
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
def upload(input_path, zip, xsiam, insecure, skip_validation, config):
    """Upload a content pack to Cortex Platform.

    INPUT_PATH can be a pack directory (Packs/MyPack) or a zip file
    (artifacts/MyPack-1.0.0.zip).

    Required environment variables:
      DEMISTO_BASE_URL - Your instance URL
      DEMISTO_API_KEY  - API key with Instance Administrator role

    For XSIAM, also set:
      XSIAM_AUTH_ID    - Authentication ID from your instance
    """
    base_url = os.environ.get("DEMISTO_BASE_URL")
    api_key = os.environ.get("DEMISTO_API_KEY")
    xsiam_auth_id = os.environ.get("XSIAM_AUTH_ID")

    if not base_url:
        click.echo("[ERROR] DEMISTO_BASE_URL environment variable not set")
        click.echo("Set it to your Cortex Platform instance URL")
        sys.exit(1)

    if not api_key:
        click.echo("[ERROR] DEMISTO_API_KEY environment variable not set")
        click.echo("Set it to a valid API key with Instance Administrator role")
        sys.exit(1)

    if xsiam and not xsiam_auth_id:
        click.echo("[ERROR] XSIAM_AUTH_ID environment variable not set")
        click.echo("For XSIAM, set the auth ID from your instance")
        sys.exit(1)

    input_file = Path(input_path)
    if not input_file.exists():
        click.echo(f"[ERROR] Path not found: {input_path}")
        sys.exit(1)

    if input_file.is_dir():
        pack_name = input_file.name
        builder = PackBuilder(config)
        mismatched = builder.check_content_naming(pack_name)
        if mismatched:
            click.echo("[WARN] Content naming mismatch detected!")
            click.echo(f"Pack name is '{pack_name}' but content items have different names:")
            for item in mismatched[:5]:
                click.echo(f"  - {item}")
            if len(mismatched) > 5:
                click.echo(f"  ... and {len(mismatched) - 5} more")
            click.echo("")
            click.echo("This may cause upload to fail. To fix, run:")
            click.echo(f"  gocortex-spellbook rename-content {pack_name}")
            click.echo(f"  gocortex-spellbook build {pack_name}")
            click.echo("")

    content_root = input_file.parent.parent.resolve() if input_file.is_dir() else Path.cwd()
    git_dir = content_root / ".git"
    git_initialized = False
    
    if not git_dir.exists():
        click.echo("Setting up temporary git repository for upload...")
        try:
            subprocess.run(
                ["git", "init"],
                cwd=str(content_root),
                capture_output=True,
                check=True
            )
            git_initialized = True
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

    cmd = ["demisto-sdk", "upload", "-i", str(input_file)]

    if zip:
        cmd.append("-z")

    if xsiam:
        cmd.append("--xsiam")

    if insecure:
        cmd.append("--insecure")

    if skip_validation:
        cmd.append("--skip-validation")

    click.echo(f"Uploading {input_path}...")
    click.echo(f"Target: {base_url}")

    try:
        env = os.environ.copy()
        env["CONTENT_PATH"] = str(content_root)
        env["DEMISTO_SDK_CONTENT_PATH"] = str(content_root)
        
        result = subprocess.run(cmd, check=False, env=env, cwd=str(content_root))
        if result.returncode == 0:
            click.echo("[OK] Upload completed successfully")
        else:
            click.echo("[FAIL] Upload failed")
            sys.exit(result.returncode)
    except FileNotFoundError:
        click.echo("[ERROR] demisto-sdk not found")
        click.echo("Install it with: pip install demisto-sdk")
        sys.exit(1)
    finally:
        if git_initialized:
            try:
                import shutil
                shutil.rmtree(git_dir)
            except Exception:
                pass


if __name__ == "__main__":
    cli()
