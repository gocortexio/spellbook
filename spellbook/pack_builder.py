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
from typing import Dict, List, Optional

import yaml

from .version_manager import VersionManager


class PackBuilder:
    """Builds and packages Cortex Platform content packs."""

    PACK_DIRECTORIES = [
        "Integrations",
        "Scripts",
        "Playbooks",
        "Reports",
        "Dashboards",
        "IncidentTypes",
        "IncidentFields",
        "Layouts",
        "Classifiers",
        "IndicatorTypes",
        "IndicatorFields",
        "Connections",
        "TestPlaybooks",
        "Wizards",
        "Jobs",
        "ParsingRules",
        "ModelingRules",
        "CorrelationRules",
        "XSIAMDashboards",
        "XSIAMReports",
        "Triggers",
        "Lists",
        "GenericDefinitions",
        "GenericFields",
        "GenericModules",
        "GenericTypes",
    ]

    def __init__(self, config_path: str = "spellbook.yaml"):
        """
        Initialise the pack builder.

        Args:
            config_path: Path to the spellbook configuration file.
        """
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent if self.config_path.parent != Path(".") else Path(".")
        self.config = self._load_config(config_path)
        
        packs_dir = self.config.get("packs_directory", "Packs")
        artifacts_dir = self.config.get("artifacts_directory", "artifacts")
        
        self.packs_dir = self.base_dir / packs_dir
        self.artifacts_dir = self.base_dir / artifacts_dir
        
        self.version_manager = VersionManager(
            self.config.get("version_tag_pattern", "{pack_name}-v{version}")
        )

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def discover_packs(self) -> List[str]:
        """
        Discover all content packs in the packs directory.

        Returns:
            List of pack names found.
        """
        if not self.packs_dir.exists():
            return []

        packs = []
        exclude = self.config.get("exclude_packs", [])

        for item in self.packs_dir.iterdir():
            if item.is_dir() and item.name not in exclude:
                metadata_file = item / "pack_metadata.json"
                if metadata_file.exists():
                    packs.append(item.name)

        return sorted(packs)

    def get_pack_path(self, pack_name: str) -> Path:
        """Get the full path to a pack directory."""
        return self.packs_dir / pack_name

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
            SystemExit: If pack does not exist.
        """
        if not self.pack_exists(pack_name):
            available = self.discover_packs()
            print(f"[ERROR] Pack '{pack_name}' not found")
            if available:
                print(f"Available packs: {', '.join(available)}")
            else:
                print("No packs found in Packs/ directory")
            raise SystemExit(1)

    def read_pack_metadata(self, pack_name: str) -> Dict:
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
                print(f"Warning: Could not parse {metadata_path}: {e}")
        return {"name": pack_name, "currentVersion": "1.0.0"}

    def update_pack_metadata(
        self,
        pack_name: str,
        updates: Dict
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
        version: Optional[str] = None
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
            print(f"Validation disabled, skipping {pack_name}")
            return True

        pack_path = self.get_pack_path(pack_name)
        content_root = pack_path.parent.parent.resolve()
        
        git_dir = content_root / ".git"
        git_initialized = False
        if not git_dir.exists():
            print("Setting up temporary git repository for validation...")
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
                     "commit", "-m", "Temporary commit for validation", "--allow-empty"],
                    cwd=str(content_root),
                    capture_output=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                print(f"Warning: Could not initialise git repository: {e}")
        
        cmd = ["demisto-sdk", "validate", "-i", str(pack_path)]

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
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")
            
            if result.returncode == 0:
                print(f"Validation passed for {pack_name}")
                return True
            else:
                print(f"Validation failed for {pack_name}")
                return False
        except FileNotFoundError:
            print("demisto-sdk not found, skipping validation")
            return True
        finally:
            if git_initialized:
                try:
                    shutil.rmtree(git_dir)
                except Exception:
                    pass

    def lint_pack(self, pack_name: str) -> bool:
        """
        Lint a pack using demisto-sdk pre-commit.

        The standalone lint command was removed from demisto-sdk
        in 2024. This method uses the pre-commit hook instead.

        Args:
            pack_name: Name of the pack to lint.

        Returns:
            True if linting passed, False otherwise.
        """
        lint_config = self.config.get("linting", {})
        if not lint_config.get("enabled", True):
            print(f"Linting disabled, skipping {pack_name}")
            return True

        pack_path = self.get_pack_path(pack_name)
        content_root = pack_path.parent.parent.resolve()
        
        git_dir = content_root / ".git"
        git_initialized = False
        if not git_dir.exists():
            print("Setting up temporary git repository for linting...")
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
                     "commit", "-m", "Temporary commit for linting", "--allow-empty"],
                    cwd=str(content_root),
                    capture_output=True,
                    check=True
                )
            except subprocess.CalledProcessError as e:
                print(f"Warning: Could not initialise git repository: {e}")

        cmd = ["demisto-sdk", "pre-commit", "-i", str(pack_path)]

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
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")
            
            if result.returncode == 0:
                print(f"Linting passed for {pack_name}")
                return True
            else:
                print(f"Linting issues in {pack_name}")
                return False
        except FileNotFoundError:
            print("demisto-sdk not found, skipping linting")
            return True
        finally:
            if git_initialized:
                try:
                    shutil.rmtree(git_dir)
                except Exception:
                    pass

    def package_pack(
        self,
        pack_name: str,
        output_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Package a pack into a zip file.

        Args:
            pack_name: Name of the pack to package.
            output_dir: Directory for output zip file.

        Returns:
            Path to created zip file, or None if packaging failed.
        """
        packaging_config = self.config.get("packaging", {})
        if not packaging_config.get("create_zip", True):
            print(f"Zip creation disabled, skipping {pack_name}")
            return None

        pack_path = self.get_pack_path(pack_name)
        if not pack_path.exists():
            print(f"Pack not found: {pack_name}")
            return None

        if output_dir is None:
            output_dir = self.artifacts_dir

        if output_dir is None:
            print(f"No output directory configured for {pack_name}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        metadata = self.read_pack_metadata(pack_name)
        version = metadata.get("currentVersion", "1.0.0")
        zip_name = f"{pack_name}-{version}.zip"
        zip_path = output_dir / zip_name

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(pack_path):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(pack_path.parent)
                    zf.write(file_path, arcname)

        print(f"Created package: {zip_path}")
        return zip_path

    def build_pack(
        self,
        pack_name: str,
        validate: bool = True,
        lint: bool = False
    ) -> Optional[Path]:
        """
        Build a complete pack (validate, lint, and package).

        Args:
            pack_name: Name of the pack to build.
            validate: Whether to run validation.
            lint: Whether to run linting.

        Returns:
            Path to created zip file, or None if build failed.
        """
        print(f"\n{'='*60}")
        print(f"Building pack: {pack_name}")
        print(f"{'='*60}")

        metadata = self.read_pack_metadata(pack_name)
        version = metadata.get("currentVersion", "1.0.0")
        print(f"Version: {version}")

        if validate:
            if not self.validate_pack(pack_name):
                print(f"Build failed for {pack_name}: validation errors")
                return None

        if lint:
            if not self.lint_pack(pack_name):
                print(f"Build failed for {pack_name}: linting errors")
                return None

        return self.package_pack(pack_name)

    def build_all_packs(
        self,
        validate: bool = True,
        lint: bool = False
    ) -> Dict[str, Optional[Path]]:
        """
        Build all discovered packs.

        Args:
            validate: Whether to run validation.
            lint: Whether to run linting.

        Returns:
            Dictionary mapping pack names to their zip file paths.
        """
        packs = self.discover_packs()
        results = {}

        for pack_name in packs:
            results[pack_name] = self.build_pack(
                pack_name,
                validate=validate,
                lint=lint
            )

        return results

    def check_content_naming(self, pack_name: str) -> List[str]:
        """
        Check if content items have mismatched naming.

        Args:
            pack_name: Name of the pack to check.

        Returns:
            List of mismatched content item paths.
        """
        pack_path = self.get_pack_path(pack_name)
        if not pack_path.exists():
            return []

        mismatched = []
        content_types = ["ModelingRules", "ParsingRules", "CorrelationRules"]

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

    def rename_content(self, pack_name: str) -> Dict[str, str]:
        """
        Rename all content items to match the pack name.

        This handles ModelingRules, ParsingRules, and CorrelationRules.
        For each content item, it renames:
        - Folder names
        - File names
        - Internal id and name fields in YAML files
        - References to .xif and .json files

        Args:
            pack_name: Name of the pack.

        Returns:
            Dictionary mapping old names to new names.
        """
        pack_path = self.get_pack_path(pack_name)
        if not pack_path.exists():
            raise FileNotFoundError(f"Pack not found: {pack_name}")

        renamed = {}

        renamed.update(self._rename_modeling_rules(pack_path, pack_name))
        renamed.update(self._rename_parsing_rules(pack_path, pack_name))
        renamed.update(self._rename_correlation_rules(pack_path, pack_name))

        return renamed

    def _rename_modeling_rules(self, pack_path: Path, pack_name: str) -> Dict[str, str]:
        """Rename ModelingRules content to match pack name."""
        renamed = {}
        rules_dir = pack_path / "ModelingRules"
        if not rules_dir.exists():
            return renamed

        new_rule_id = f"{pack_name}ModelingRule"
        new_folder = rules_dir / new_rule_id

        for item in list(rules_dir.iterdir()):
            if item.is_dir() and item.name != new_rule_id:
                old_name = item.name
                old_id = old_name

                for f in list(item.iterdir()):
                    if f.suffix == ".yml":
                        self._update_yaml_id(f, new_rule_id, pack_name, "modeling")
                        new_fname = f"{new_rule_id}.yml"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname
                    elif f.suffix == ".xif":
                        new_fname = f"{new_rule_id}.xif"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname
                    elif f.name.endswith("_schema.json"):
                        new_fname = f"{new_rule_id}_schema.json"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname

                if item.name != new_rule_id:
                    item.rename(new_folder)
                    renamed[old_name] = new_rule_id

        return renamed

    def _rename_parsing_rules(self, pack_path: Path, pack_name: str) -> Dict[str, str]:
        """Rename ParsingRules content to match pack name."""
        renamed = {}
        rules_dir = pack_path / "ParsingRules"
        if not rules_dir.exists():
            return renamed

        new_rule_id = f"{pack_name}ParsingRule"
        new_folder = rules_dir / new_rule_id

        for item in list(rules_dir.iterdir()):
            if item.is_dir() and item.name != new_rule_id:
                old_name = item.name

                for f in list(item.iterdir()):
                    if f.suffix == ".yml":
                        self._update_yaml_id(f, new_rule_id, pack_name, "parsing")
                        new_fname = f"{new_rule_id}.yml"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname
                    elif f.suffix == ".xif":
                        new_fname = f"{new_rule_id}.xif"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname
                    elif f.name.endswith("_samples.json"):
                        new_fname = f"{new_rule_id}_samples.json"
                        if f.name != new_fname:
                            new_path = f.parent / new_fname
                            f.rename(new_path)
                            renamed[f.name] = new_fname

                if item.name != new_rule_id:
                    item.rename(new_folder)
                    renamed[old_name] = new_rule_id

        return renamed

    def _rename_correlation_rules(self, pack_path: Path, pack_name: str) -> Dict[str, str]:
        """Rename CorrelationRules content to match pack name."""
        renamed = {}
        rules_dir = pack_path / "CorrelationRules"
        if not rules_dir.exists():
            return renamed

        for item in list(rules_dir.iterdir()):
            if item.is_file() and item.suffix in [".yml", ".yaml"]:
                with open(item, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)

                if content:
                    old_id = content.get("global_rule_id", "")
                    if old_id and not old_id.startswith(pack_name):
                        rule_suffix = old_id.split("_", 1)[-1] if "_" in old_id else "Rule"
                        new_id = f"{pack_name}_{rule_suffix}"
                        content["global_rule_id"] = new_id

                        vendor = pack_name.lower()
                        if "dataset" in content:
                            content["dataset"] = f"{vendor}_raw"
                        if "xql_query" in content:
                            old_query = content["xql_query"]
                            lines = old_query.split("\n")
                            if lines and lines[0].strip().startswith("dataset"):
                                lines[0] = f"  dataset = {vendor}_raw"
                            content["xql_query"] = "\n".join(lines)

                        with open(item, "w", encoding="utf-8") as f:
                            yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

                        new_fname = f"{new_id}.yml"
                        if item.name != new_fname:
                            new_path = item.parent / new_fname
                            item.rename(new_path)
                            renamed[item.name] = new_fname

        return renamed

    def _update_yaml_id(self, yaml_path: Path, new_id: str, pack_name: str, rule_type: str) -> None:
        """Update id and name fields in a YAML file."""
        with open(yaml_path, "r", encoding="utf-8") as f:
            content = yaml.safe_load(f)

        if content:
            content["id"] = new_id
            content["name"] = f"{pack_name} {rule_type.title()} Rule"
            content["rules"] = f"{new_id}.xif"

            if rule_type == "modeling":
                content["schema"] = f"{new_id}_schema.json"
            elif rule_type == "parsing":
                content["samples"] = f"{new_id}_samples.json"

            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(content, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
