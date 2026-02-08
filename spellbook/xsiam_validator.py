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
