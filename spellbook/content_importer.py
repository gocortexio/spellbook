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

from . import HOUSE_FROM_VERSION


class CorrelationImporter:
    """Import correlation rules from JSON exports to YAML files.

    Only fields that are meaningless outside the exporting tenant are
    removed. Everything else is preserved verbatim, including fields that
    demisto-sdk's strict model does not declare (action, alert_domain,
    alert_type, is_enabled, timezone). The Cortex Platform stores and uses
    those fields, and `demisto-sdk validate` does not reject them, so
    stripping them would silently discard real behaviour: a rule could
    install disabled, or land in the wrong alert domain.
    """

    FIELDS_TO_REMOVE = {
        # Tenant-local identifier, reassigned on install.
        "rule_id",
        # Superseded by crontab/execution_mode/search_window; leaving it in
        # has been observed to fail upload (see the XSIAM validator rule).
        "simple_schedule",
        "lookup_mapping",
    }

    FIELDS_TO_PRESERVE_NULL = {
        "alert_type",
        "user_defined_severity",
        "user_defined_category",
    }

    # Used when a rule name contains no character that survives sanitisation.
    # Without it the stem was empty and the file became ".yml", a dotfile.
    FALLBACK_RULE_STEM = "correlation_rule"

    FIELDS_TO_ADD = {
        "global_rule_id": lambda: str(uuid.uuid4()),
        "fromversion": lambda: HOUSE_FROM_VERSION,
    }

    # A tenant sets `timezone` to wherever its operators are, and the export
    # carries that value out with the rule. It is preserved rather than
    # stripped - see the class docstring; the Platform schedules on it, and
    # deleting it would silently change when a rule fires.
    #
    # But an IANA region/city value states where this estate is, and a pack
    # goes to a public marketplace. A reviewer on a public pull request spotted
    # one before the estate's own release gate did. Import is the last point
    # where the author can still decide, so it is named here rather than
    # deleted here.
    #
    # UTC and the fixed offsets disclose nothing, so they are not flagged.
    TENANT_LOCATION_FIELD = "timezone"
    NON_DISCLOSING_TIMEZONES = {"UTC", "GMT", "Z", "UCT", "Universal", "Zulu"}

    def _check_location_disclosure(self, rule: dict) -> list[str]:
        """Warn when a rule carries a timezone that names a place.

        Returns a list so a future second disclosing field costs one append
        rather than a second call site.
        """
        value = rule.get(self.TENANT_LOCATION_FIELD)
        if not isinstance(value, str):
            return []

        candidate = value.strip()
        if not candidate or candidate in self.NON_DISCLOSING_TIMEZONES:
            return []
        # Fixed offsets ("+10:00", "Etc/GMT-10") name no place.
        if candidate.startswith(("+", "-")) or candidate.startswith("Etc/"):
            return []
        if "/" not in candidate:
            return []

        return [
            f"{self.TENANT_LOCATION_FIELD} is '{candidate}', which names a "
            f"region and says where this tenant is. It is kept because the "
            f"Platform schedules on it, but it ships in the pack - remove or "
            f"replace it before publishing anywhere public"
        ]

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
        if correlation_dir.is_symlink():
            raise ValueError(
                "CorrelationRules directory is a symlink; refusing to write "
                "through it to prevent path escape"
            )
        correlation_dir.mkdir(exist_ok=True)

        results = []
        # Filenames allocated so far in THIS batch. Two rule names that
        # sanitise to the same stem must not resolve by one overwriting the
        # other, which is what happened and what the summary did not say.
        taken: set[str] = set()
        for i, rule in enumerate(rules, 1):
            try:
                warnings = self._check_location_disclosure(rule)
                if sanitised:
                    affected = self._check_control_characters(rule)
                    if affected:
                        warnings.append(f"control characters found in: {', '.join(affected)}")
                result = self._process_rule(
                    rule, correlation_dir, i, len(rules), taken
                )
                expected = self._generate_filename(rule.get("name", ""))
                if result["filename"] != expected:
                    warnings.append(
                        f"name collides with another rule in this import, so "
                        f"it was written as {result['filename']} rather than "
                        f"{expected} - both rules are kept, but check the names"
                    )
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
        self,
        rule: dict,
        output_dir: Path,
        index: int,
        total: int,
        taken: set[str] | None = None,
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
        filename = self._generate_filename(name, taken)
        file_path = output_dir / filename

        resolved_file = file_path.resolve()
        resolved_output_dir = output_dir.resolve()
        try:
            resolved_file.relative_to(resolved_output_dir)
        except ValueError:
            raise ValueError(
                f"Generated file path '{file_path}' resolves outside the "
                f"output directory '{output_dir}'; refusing to write"
            )

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
            cleaned[key] = self._normalise_line_endings(value, field_name=key)

        if cleaned.get("severity") != "User Defined":
            cleaned.pop("user_defined_severity", None)
        if cleaned.get("alert_category") != "User Defined":
            cleaned.pop("user_defined_category", None)

        # suppression_fields is left in whatever form the export used. The
        # platform stores it as an array and demisto-sdk accepts that, even
        # though the SDK's strict model declares it as a string; rewriting it
        # would change content to satisfy a model the SDK does not enforce.

        for field_name, generator in self.FIELDS_TO_ADD.items():
            if field_name not in cleaned:
                cleaned[field_name] = generator()

        return cleaned

    XQL_FIELDS = {"xql_query", "search_query"}

    def _normalise_line_endings(self, value: Any, field_name: str | None = None) -> Any:
        """Normalise line endings in string values.

        Strips carriage returns from all strings. For XQL query fields,
        also collapses consecutive blank lines and trims whitespace.
        Recurses into dicts and lists to catch nested values.

        Args:
            value: Any value from a parsed rule.
            field_name: Name of the field being processed.

        Returns:
            Value with normalised line endings.
        """
        if isinstance(value, str):
            result = value.replace("\r\n", "\n").replace("\r", "\n")
            if field_name in self.XQL_FIELDS:
                result = re.sub(r"\n{2,}", "\n", result)
                result = "\n".join(line.rstrip() for line in result.split("\n"))
                result = result.strip()
            return result
        if isinstance(value, dict):
            return {k: self._normalise_line_endings(v, field_name=k) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalise_line_endings(item, field_name=field_name) for item in value]
        return value

    def _generate_filename(self, name: str, taken: set[str] | None = None) -> str:
        """Generate a unique, valid filename from the rule name.

        Stripping everything outside [A-Za-z0-9_-] makes the mapping lossy, so
        distinct rule names collided: "Portkey: Key Removed" and "Portkey Key
        Removed" both reduced to Portkey_Key_Removed.yml, the second overwrote
        the first, and the summary still reported both as imported. A batch of
        50 exported rules could ship 48.

        A name with no ASCII alphanumerics at all - any wholly non-Latin name -
        reduced to the empty string and produced ".yml", a hidden dotfile that
        no later stage sees.

        `taken` carries the filenames already allocated in this batch, so a
        collision is disambiguated rather than resolved by overwriting. The
        caller reports the disambiguation.

        Args:
            name: Rule name.
            taken: Filenames already allocated in this import.

        Returns:
            Valid filename with .yml extension, unique within `taken`.
        """
        stem = name.replace(" - ", "___")
        stem = stem.replace(" ", "_")
        stem = re.sub(r"[^a-zA-Z0-9_\-]", "", stem)
        # Never a dotfile, never empty.
        stem = stem.lstrip("._-")
        if not stem:
            stem = self.FALLBACK_RULE_STEM

        if taken is None:
            return f"{stem}.yml"

        candidate = f"{stem}.yml"
        suffix = 2
        while candidate in taken:
            candidate = f"{stem}_{suffix}.yml"
            suffix += 1
        taken.add(candidate)
        return candidate

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
