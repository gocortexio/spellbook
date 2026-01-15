"""
XSIAM Validator Module

Provides additional validation rules that catch XSIAM-specific issues
not detected by demisto-sdk. These rules are based on actual upload
failures encountered when pushing content to XSIAM.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class ValidationIssue:
    """Represents a validation issue found in content."""
    rule_name: str
    severity: str  # "error" or "warning"
    file_path: str
    message: str
    line_number: Optional[int] = None


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

    RULES: List[ValidationRule] = [
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

    def __init__(self, packs_dir: Path):
        """
        Initialise the XSIAM validator.
        
        Args:
            packs_dir: Path to the Packs directory.
        """
        self.packs_dir = packs_dir

    def validate_pack(self, pack_name: str) -> List[ValidationIssue]:
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
        
        return issues

    def validate_all_packs(self) -> Dict[str, List[ValidationIssue]]:
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
    ) -> List[ValidationIssue]:
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

    def format_issues(self, issues: List[ValidationIssue]) -> str:
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
                lines.append(f"  [ERROR] {location}")
                lines.append(f"          {issue.message}")
        
        if warnings:
            if errors:
                lines.append("")
            lines.append("XSIAM Validation Warnings:")
            for issue in warnings:
                location = f"{issue.file_path}"
                if issue.line_number:
                    location += f":{issue.line_number}"
                lines.append(f"  [WARN] {location}")
                lines.append(f"         {issue.message}")
        
        return "\n".join(lines)
