# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Pack Builder Module

Handles discovery, validation, and packaging of Cortex Platform content packs.
"""

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import click
import yaml

from .pack_tests import run_pack_tests
from .python_lint import run_ruff_check
from .version_manager import VersionManager


EXCLUDED_PACKS = ["SamplePack"]


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

    def read_pack_metadata(self, pack_name: str) -> dict:
        """
        Read pack metadata from pack_metadata.json.

        Args:
            pack_name: Name of the pack.

        Returns:
            Dictionary containing pack metadata.
        """
        metadata_path = self.get_pack_path(pack_name) / "pack_metadata.json"
        if metadata_path.exists():
            try:
                with open(metadata_path, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                if content.strip():
                    return json.loads(content)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                click.echo(f"[WARN] {metadata_path}: could not parse ({e})")
        return {"name": pack_name, "currentVersion": "1.0.0"}

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

    def validate_pack(self, pack_name: str) -> bool:
        """
        Validate a pack using demisto-sdk.

        Args:
            pack_name: Name of the pack to validate.

        Returns:
            True if validation passed, False otherwise.
        """
        validation_config = self.config.get("validation", {})
        if not validation_config.get("enabled", True):
            click.echo(f"Validation disabled, skipping {pack_name}")
            return True

        pack_path = self.get_pack_path(pack_name)

        # Lint Python content with the store pipeline's ruff configuration.
        # demisto-sdk validate does not run ruff, so without this a pack can
        # build clean locally and then fail official store submission.
        ruff_passed = run_ruff_check(pack_path)

        # Run the pack's own unit tests the way the pipeline does. Same
        # reasoning as the lint above: validate does not run them, so a pack
        # could pass here and fail the pipeline's test stage.
        tests_passed = run_pack_tests(pack_path)

        content_root = pack_path.parent.parent.resolve()
        
        git_dir = content_root / ".git"
        git_initialised = False
        if not git_dir.exists():
            click.echo("Setting up temporary git repository for validation...")
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
                click.echo(f"[WARN] Could not initialise git repository: {e}")
        
        # The input path must be relative to the content root (the process
        # cwd). An absolute -i path makes demisto-sdk resolve its internal
        # CONTENT_PATH to an empty string, which later crashes validators
        # with "is not in the subpath of ''".
        cmd = [
            "demisto-sdk", "validate",
            "-i", str(pack_path.relative_to(content_root)),
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
            click.echo(result.stdout, nl=False)
            if result.stderr:
                click.echo(result.stderr, nl=False)
            
            if result.returncode == 0:
                if not ruff_passed:
                    click.echo(f"Validation failed for {pack_name} (Python lint)")
                    return False
                if not tests_passed:
                    click.echo(f"Validation failed for {pack_name} (unit tests)")
                    return False
                click.echo(f"Validation passed for {pack_name}")
                self._check_gitkeep_files(pack_name)
                return True
            else:
                click.echo(f"Validation failed for {pack_name}")
                return False
        except FileNotFoundError:
            click.echo("[WARN] demisto-sdk not found, skipping validation")
            return ruff_passed and tests_passed
        finally:
            if git_initialised:
                try:
                    shutil.rmtree(git_dir)
                except Exception:
                    pass

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

