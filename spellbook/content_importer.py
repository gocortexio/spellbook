# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Content Importer Module

Handles importing content exported from the Cortex Platform back into
content packs. Supports converting JSON exports to YAML format with
appropriate field transformations.
"""

import json
import re
import uuid
from pathlib import Path
from typing import Any

import yaml


class CorrelationImporter:
    """Import correlation rules from JSON exports to YAML files."""

    FIELDS_TO_REMOVE = {
        "rule_id",
        "simple_schedule",
        "user_defined_severity",
        "user_defined_category",
        "lookup_mapping",
    }

    FIELDS_TO_PRESERVE_NULL = {
        "alert_type",
    }

    FIELDS_TO_ADD = {
        "global_rule_id": lambda: str(uuid.uuid4()),
        "fromversion": lambda: "8.4.0",
    }

    def __init__(self, packs_dir: Path):
        """Initialise the importer.

        Args:
            packs_dir: Path to the Packs directory.
        """
        self.packs_dir = packs_dir

    def import_from_json(self, json_content: str, pack_name: str) -> list[dict]:
        """Import correlation rules from JSON content.

        Attempts strict JSON parsing first. If the content contains
        unescaped control characters, retries with strict=False and
        flags affected fields per rule.

        Args:
            json_content: JSON string containing an array of correlation rules.
            pack_name: Target pack name.

        Returns:
            List of results with file paths and status.
        """
        sanitised = False
        try:
            rules = json.loads(json_content)
        except json.JSONDecodeError as e:
            if "control character" in str(e).lower() or "invalid control" in str(e).lower():
                try:
                    rules = json.loads(json_content, strict=False)
                    sanitised = True
                except json.JSONDecodeError as e2:
                    raise ValueError(f"Invalid JSON: {e2}")
            else:
                raise ValueError(f"Invalid JSON: {e}")

        if not isinstance(rules, list):
            raise ValueError("JSON must be an array of correlation rules")

        if not rules:
            raise ValueError("JSON array is empty")

        pack_path = self.packs_dir / pack_name
        if not pack_path.exists():
            raise ValueError(f"Pack not found: {pack_name}")

        correlation_dir = pack_path / "CorrelationRules"
        correlation_dir.mkdir(exist_ok=True)

        results = []
        for i, rule in enumerate(rules, 1):
            try:
                warnings = []
                if sanitised:
                    affected = self._check_control_characters(rule)
                    if affected:
                        warnings.append(f"control characters found in: {', '.join(affected)}")
                result = self._process_rule(rule, correlation_dir, i, len(rules))
                result["warnings"] = warnings
                results.append(result)
            except Exception as e:
                results.append({
                    "index": i,
                    "total": len(rules),
                    "name": rule.get("name", "unknown"),
                    "success": False,
                    "error": str(e),
                    "warnings": [],
                })

        return results

    def _check_control_characters(self, rule: dict) -> list[str]:
        """Check which fields contain control characters.

        Args:
            rule: Rule dictionary.

        Returns:
            List of field names containing control characters.
        """
        affected = []
        for key, value in rule.items():
            if isinstance(value, str):
                for ch in value:
                    if ord(ch) < 32 and ch not in ('\n', '\r', '\t'):
                        affected.append(key)
                        break
        return affected

    def _process_rule(
        self, rule: dict, output_dir: Path, index: int, total: int
    ) -> dict:
        """Process a single correlation rule.

        Args:
            rule: Rule dictionary from JSON.
            output_dir: Directory to write YAML file.
            index: Rule index (1-based).
            total: Total number of rules.

        Returns:
            Result dictionary with status.
        """
        name = rule.get("name")
        if not name:
            raise ValueError("Rule missing 'name' field")

        cleaned_rule = self._clean_rule(rule)
        filename = self._generate_filename(name)
        file_path = output_dir / filename
        overwritten = file_path.exists()

        yaml_content = self._to_yaml(cleaned_rule)
        file_path.write_text(yaml_content, encoding="utf-8")

        return {
            "index": index,
            "total": total,
            "name": name,
            "filename": filename,
            "path": str(file_path),
            "success": True,
            "overwritten": overwritten,
        }

    def _clean_rule(self, rule: dict) -> dict:
        """Remove platform fields and add required fields.

        Args:
            rule: Original rule dictionary.

        Returns:
            Cleaned rule dictionary.
        """
        cleaned = {}

        for key, value in rule.items():
            if key in self.FIELDS_TO_REMOVE:
                continue
            if value is None and key not in self.FIELDS_TO_PRESERVE_NULL:
                continue
            cleaned[key] = value

        for field_name, generator in self.FIELDS_TO_ADD.items():
            if field_name not in cleaned:
                cleaned[field_name] = generator()

        return cleaned

    def _generate_filename(self, name: str) -> str:
        """Generate a valid filename from the rule name.

        Converts spaces to underscores, dashes to triple underscores,
        and removes invalid characters.

        Args:
            name: Rule name.

        Returns:
            Valid filename with .yml extension.
        """
        filename = name.replace(" - ", "___")
        filename = filename.replace(" ", "_")
        filename = re.sub(r"[^a-zA-Z0-9_\-]", "", filename)
        return f"{filename}.yml"

    def _to_yaml(self, data: dict) -> str:
        """Convert dictionary to YAML string.

        Uses custom representer for multiline strings.

        Args:
            data: Dictionary to convert.

        Returns:
            YAML string.
        """

        class MultilineDumper(yaml.SafeDumper):
            pass

        def str_representer(dumper, data):
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

        MultilineDumper.add_representer(str, str_representer)

        return yaml.dump(
            data,
            Dumper=MultilineDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
