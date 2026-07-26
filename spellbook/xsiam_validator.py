# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
XSIAM Validator Module

Provides additional validation rules that catch XSIAM-specific issues
not detected by demisto-sdk. These rules are based on actual upload
failures encountered when pushing content to XSIAM.
"""

import re
from pathlib import Path

from dataclasses import dataclass

import yaml

from .xdm_fields import scan_unmappable_fields


# Content directories whose files must be named `<PackFolder>_<something>`
# with an allowed suffix. Mirrors XSIAM_DEPTH_1_CHECKS in demisto-sdk's
# scripts/validate_content_path.py. That rule is enforced by the official
# store pipeline through the `validate-content-path` pre-commit hook, not by
# `demisto-sdk validate`, so it is checked here instead.
XSIAM_DEPTH_ONE_PREFIX_DIRS = {
    "CorrelationRules": {".yml"},
    "XSIAMDashboards": {".json", ".png"},
    "XSIAMReports": {".json", ".png"},
}

# Content directories whose YAML items have a demisto-sdk strict model.
# Maps the directory to its model module, model name, and whether the items
# sit in package subdirectories. `demisto-sdk validate` does not enforce
# these models in practice (a rule missing a required field, or carrying a
# field the model forbids, passes), so they are applied here.
STRICT_MODEL_SOURCES = {
    "CorrelationRules": (
        "demisto_sdk.commands.content_graph.strict_objects.correlation_rule",
        "StrictCorrelationRule",
        False,
    ),
    "ModelingRules": (
        "demisto_sdk.commands.content_graph.strict_objects.modeling_rule",
        "StrictModelingRule",
        True,
    ),
    "ParsingRules": (
        "demisto_sdk.commands.content_graph.strict_objects.parsing_rule",
        "StrictParsingRule",
        True,
    ),
}


@dataclass
class ValidationIssue:
    """Represents a validation issue found in content."""
    rule_name: str
    severity: str  # "error" or "warning"
    file_path: str
    message: str
    line_number: int | None = None


@dataclass
class ValidationRule:
    """Defines a validation rule for content checking."""
    name: str
    content_type: str  # ParsingRules, CorrelationRules, etc.
    file_pattern: str  # *.xif, *.yml, etc.
    pattern: str  # Regex pattern to detect issues
    message: str
    severity: str = "error"


class XSIAMValidator:
    """
    Validates content packs against XSIAM-specific requirements.
    
    This validator catches issues that demisto-sdk does not detect
    but cause XSIAM upload failures (typically error 101704).
    """

    RULES: list[ValidationRule] = [
        # Parsing Rules checks
        ValidationRule(
            name="invalid_ingest_content_id",
            content_type="ParsingRules",
            file_pattern="*.xif",
            pattern=r'\[INGEST:[^\]]*content_id\s*=',
            message="Invalid field 'content_id' in INGEST directive - XSIAM does not support this field",
            severity="error"
        ),
        
        # Correlation Rules checks
        ValidationRule(
            name="invalid_simple_schedule",
            content_type="CorrelationRules",
            file_pattern="*.yml",
            pattern=r'^\s*simple_schedule\s*:',
            message="Invalid field 'simple_schedule' in correlation rule - use crontab, execution_mode, and search_window instead",
            severity="error"
        ),
        ValidationRule(
            name="parentheses_in_correlation_name",
            content_type="CorrelationRules",
            file_pattern="*.yml",
            pattern=r'^\s*name\s*:\s*.*[\(\)]',
            message="Parentheses in correlation rule name may cause XSIAM issues - use hyphens instead",
            severity="warning"
        ),
        
    ]
    
    # Content types to check for filename issues
    FILENAME_CHECK_DIRECTORIES = [
        "XSIAMDashboards",
        "XSIAMReports",
        "CorrelationRules",
        "ParsingRules",
        "ModelingRules",
        "Playbooks",
        "Scripts",
        "Integrations",
        "Triggers",
        "Jobs",
        "XDRCTemplates",
    ]

    def __init__(self, packs_dir: Path):
        """
        Initialise the XSIAM validator.
        
        Args:
            packs_dir: Path to the Packs directory.
        """
        self.packs_dir = packs_dir

    def validate_pack(self, pack_name: str) -> list[ValidationIssue]:
        """
        Validate a single pack against XSIAM rules.
        
        Args:
            pack_name: Name of the pack to validate.
            
        Returns:
            List of validation issues found.
        """
        pack_path = self.packs_dir / pack_name
        if not pack_path.exists():
            return []
        
        issues = []
        
        for rule in self.RULES:
            rule_issues = self._check_rule(pack_path, rule)
            issues.extend(rule_issues)
        
        # Check filenames for problematic characters
        filename_issues = self._check_filenames(pack_path)
        issues.extend(filename_issues)

        issues.extend(self._check_unmappable_xdm_fields(pack_path))

        issues.extend(self._check_depth_one_filenames(pack_path))

        issues.extend(self._check_strict_schemas(pack_path))

        return issues

    def _check_depth_one_filenames(self, pack_path: Path) -> list[ValidationIssue]:
        """Check that XSIAM depth-one items are named `<PackFolder>_...`.

        The official store pipeline rejects a correlation rule, XSIAM
        dashboard, or XSIAM report whose filename stem does not begin with the
        pack folder name followed by an underscore, or whose suffix is not one
        the content type allows. Reported as a warning: the item still
        installs on a tenant, but store submission would be rejected.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        issues = []
        pack_name = pack_path.name

        for content_type, allowed_suffixes in XSIAM_DEPTH_ONE_PREFIX_DIRS.items():
            content_dir = pack_path / content_type
            if not content_dir.exists():
                continue

            # The rule applies to files directly inside the content folder.
            for file_path in sorted(content_dir.iterdir()):
                if not file_path.is_file() or file_path.name == ".gitkeep":
                    continue

                relative_path = str(file_path.relative_to(pack_path.parent))

                if file_path.suffix not in allowed_suffixes:
                    allowed = ", ".join(sorted(allowed_suffixes))
                    issues.append(ValidationIssue(
                        rule_name="xsiam_filename_suffix",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                            f"{content_type} only accepts {allowed} files - the "
                            f"official content store rejects other suffixes"
                        ),
                    ))
                elif not file_path.stem.startswith(f"{pack_name}_"):
                    issues.append(ValidationIssue(
                        rule_name="xsiam_filename_pack_prefix",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                            f"filename must start with '{pack_name}_' - the "
                            f"official content store rejects mismatched names"
                        ),
                    ))

        return issues

    def _load_strict_models(self, content_types: list[str]) -> dict:
        """Import the demisto-sdk strict models for the given content types.

        Returns an empty mapping when demisto-sdk is unavailable, so the
        check degrades to a no-op rather than failing validation.
        """
        import importlib

        models = {}
        for content_type in content_types:
            module_name, model_name, _ = STRICT_MODEL_SOURCES[content_type]
            try:
                module = importlib.import_module(module_name)
                models[content_type] = getattr(module, model_name)
            except Exception:
                continue
        return models

    def _check_strict_schemas(self, pack_path: Path) -> list[ValidationIssue]:
        """Check YAML content items against the demisto-sdk strict models.

        Catches required fields that are missing and fields the model
        forbids. Reported as warnings because the models are stricter than
        what a tenant accepts at install time, but match what the official
        content store enforces.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        candidates: dict[str, list[Path]] = {}
        for content_type, (_, _, nested) in STRICT_MODEL_SOURCES.items():
            content_dir = pack_path / content_type
            if not content_dir.exists():
                continue
            paths = (
                sorted(content_dir.rglob("*.yml"))
                if nested
                else sorted(content_dir.glob("*.yml"))
            )
            if paths:
                candidates[content_type] = paths

        if not candidates:
            return []

        models = self._load_strict_models(list(candidates))
        if not models:
            return []

        issues = []
        for content_type, paths in candidates.items():
            model = models.get(content_type)
            if model is None:
                continue

            for file_path in paths:
                try:
                    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, yaml.YAMLError):
                    # Malformed or unreadable files are demisto-sdk's to report.
                    continue
                if not isinstance(data, dict):
                    continue

                try:
                    model.parse_obj(data)
                except Exception as exc:
                    errors = getattr(exc, "errors", None)
                    if not callable(errors):
                        continue
                    relative_path = str(file_path.relative_to(pack_path.parent))
                    for error in errors():
                        field = ".".join(str(part) for part in error.get("loc", ()))
                        issues.append(ValidationIssue(
                            rule_name="strict_schema_mismatch",
                            severity="warning",
                            file_path=relative_path,
                            message=(
                                f"'{field}': {error.get('msg', 'schema mismatch')} "
                                f"(demisto-sdk {model.__name__})"
                            ),
                        ))

        return issues

    def _check_unmappable_xdm_fields(self, pack_path: Path) -> list[ValidationIssue]:
        """Check modelling rule XIF files for platform-derived XDM fields.

        Certain XDM fields are valid in the schema but cannot be mapping
        targets in a data model rule; assigning to one leaves the pack in
        an orphaned state on the tenant (the rule installs but never
        compiles). Assignments are errors. Any other occurrence inside a
        modelling rule is unusual and reported as a warning. Other content
        types (correlation rule XQL, investigation queries) legitimately
        reference these fields and are not checked.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        issues = []
        rules_dir = pack_path / "ModelingRules"
        if not rules_dir.exists():
            return issues

        for xif_path in sorted(rules_dir.rglob("*.xif")):
            if not xif_path.is_file():
                continue
            try:
                content = xif_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            relative_path = str(xif_path.relative_to(pack_path.parent))
            for finding in scan_unmappable_fields(content):
                if finding["assignment"]:
                    issues.append(ValidationIssue(
                        rule_name="unmappable_xdm_field_assignment",
                        severity="error",
                        file_path=relative_path,
                        message=(
                            f"'{finding['field']}' is a platform-derived XDM field and "
                            f"cannot be a mapping target in a data model rule - remove "
                            f"the assignment or the pack installs in an orphaned state"
                        ),
                        line_number=finding["line"],
                    ))
                else:
                    issues.append(ValidationIssue(
                        rule_name="unmappable_xdm_field_reference",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                            f"'{finding['field']}' is a platform-derived XDM field that "
                            f"a data model rule cannot populate - confirm this "
                            f"occurrence is intentional"
                        ),
                        line_number=finding["line"],
                    ))

        return issues
    
    def _check_filenames(self, pack_path: Path) -> list[ValidationIssue]:
        """
        Check filenames for problematic characters.
        
        Detects spaces and other problematic characters in content filenames
        that may cause issues with XSIAM uploads.
        
        Args:
            pack_path: Path to the pack directory.
            
        Returns:
            List of validation issues for problematic filenames.
        """
        issues = []
        
        for content_type in self.FILENAME_CHECK_DIRECTORIES:
            content_dir = pack_path / content_type
            if not content_dir.exists():
                continue
            
            for file_path in content_dir.rglob("*"):
                if not file_path.is_file():
                    continue
                
                # Skip .gitkeep files
                if file_path.name == ".gitkeep":
                    continue
                
                filename = file_path.name
                relative_path = str(file_path.relative_to(pack_path.parent))
                
                # Check for spaces in filename
                if " " in filename:
                    issues.append(ValidationIssue(
                        rule_name="filename_contains_space",
                        severity="error",
                        file_path=relative_path,
                        message="Filename contains spaces - rename file using underscores or hyphens only"
                    ))
                
                # Check for mixed separators (both underscore and hyphen)
                has_underscore = "_" in filename.replace(".yml", "").replace(".json", "").replace(".xif", "").replace(".md", "")
                has_hyphen = "-" in filename.replace(".yml", "").replace(".json", "").replace(".xif", "").replace(".md", "")
                if has_underscore and has_hyphen:
                    issues.append(ValidationIssue(
                        rule_name="filename_mixed_separators",
                        severity="warning",
                        file_path=relative_path,
                        message="Filename uses mixed separators (underscores and hyphens) - consider using consistent separators"
                    ))
        
        return issues

    def validate_all_packs(self) -> dict[str, list[ValidationIssue]]:
        """
        Validate all packs in the packs directory.
        
        Returns:
            Dictionary mapping pack names to their validation issues.
        """
        results = {}
        
        if not self.packs_dir.exists():
            return results
        
        for pack_dir in self.packs_dir.iterdir():
            if pack_dir.is_dir() and not pack_dir.name.startswith('.'):
                issues = self.validate_pack(pack_dir.name)
                if issues:
                    results[pack_dir.name] = issues
        
        return results

    def _check_rule(
        self,
        pack_path: Path,
        rule: ValidationRule
    ) -> list[ValidationIssue]:
        """
        Check a single rule against a pack.
        
        Args:
            pack_path: Path to the pack directory.
            rule: The validation rule to check.
            
        Returns:
            List of issues found for this rule.
        """
        issues = []
        
        # Find the content type directory
        content_dir = pack_path / rule.content_type
        if not content_dir.exists():
            return []
        
        # Find all matching files
        pattern = rule.file_pattern
        for file_path in content_dir.rglob(pattern):
            if not file_path.is_file():
                continue
            
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception:
                continue
            
            # Check each line for the pattern
            compiled_pattern = re.compile(rule.pattern, re.MULTILINE)
            
            for line_num, line in enumerate(content.splitlines(), start=1):
                if compiled_pattern.search(line):
                    relative_path = str(file_path.relative_to(pack_path.parent))
                    issues.append(ValidationIssue(
                        rule_name=rule.name,
                        severity=rule.severity,
                        file_path=relative_path,
                        message=rule.message,
                        line_number=line_num
                    ))
        
        return issues

    def format_issues(self, issues: list[ValidationIssue]) -> str:
        """
        Format validation issues for display.
        
        Args:
            issues: List of validation issues.
            
        Returns:
            Formatted string for display.
        """
        if not issues:
            return ""
        
        lines = []
        errors = [i for i in issues if i.severity == "error"]
        warnings = [i for i in issues if i.severity == "warning"]
        
        if errors:
            lines.append("XSIAM Validation Errors:")
            for issue in errors:
                location = f"{issue.file_path}"
                if issue.line_number:
                    location += f":{issue.line_number}"
                lines.append(f"[ERROR] {location}: {issue.message}")
        
        if warnings:
            if errors:
                lines.append("")
            lines.append("XSIAM Validation Warnings:")
            for issue in warnings:
                location = f"{issue.file_path}"
                if issue.line_number:
                    location += f":{issue.line_number}"
                lines.append(f"[WARN] {location}: {issue.message}")
        
        return "\n".join(lines)
