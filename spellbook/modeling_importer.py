# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Modeling Rule Importer Module

Imports data model (XDM) rules copied out of a Cortex Platform tenant back
into a content pack. The input is raw XIF rule text beginning with a
[MODEL: dataset="..."] header.

Unlike a correlation rule, which is a single flat YAML file, a modelling rule
is a three-file package:

    ModelingRules/<Stem>/
        <Stem>.yml
        <Stem>.xif
        <Stem>_schema.json

demisto-sdk binds the sidecars to the rule by filename stem, so all three
stems must agree or the .xif and schema are silently ignored and the rule
ships unmapped.
"""

import json
import re
from pathlib import Path

import yaml

from .xdm_fields import scan_unmappable_fields


# Mirrors XifFile.get_dataset_from_xif in demisto-sdk
# (demisto_sdk/commands/content_graph/parsers/related_files.py). Validator
# MR107 compares the datasets this expression finds in the .xif against the
# top-level keys of _schema.json, so the importer must extract them
# identically or the rule it writes fails validation. Note this matches every
# "dataset =" in the file, not only the MODEL header.
SDK_DATASET_PATTERN = re.compile(r'dataset[ ]?=[ ]?(["a-zA-Z_0-9]+)')

MODEL_HEADER_PATTERN = re.compile(r"\[\s*MODEL\s*:", re.IGNORECASE)

# demisto-sdk constants (commands/common/constants.py). Validator MR108
# requires the rule id and name to carry these suffixes.
MODELING_RULE_ID_SUFFIX = "ModelingRule"
MODELING_RULE_NAME_SUFFIX = "Modeling Rule"

# Only these are accepted by validator MR106 and StrictModelingRuleSchema.
SCHEMA_FILE_VALID_ATTRIBUTES_TYPE = {"string", "int", "float", "datetime", "boolean"}
DEFAULT_COLUMN_TYPE = "string"

DEFAULT_FROM_VERSION = "8.3.0"

RAW_LOG_COLUMN = "_raw_log"

COMMENT_PATTERN = re.compile(r"//[^\n]*")
STRING_LITERAL_PATTERN = re.compile(r'"(?:[^"\\]|\\.)*"')
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
# A left-hand side is an identifier followed by a single '=' that is not part
# of a comparison operator (==, !=, <=, >=) or the '=' of a keyword argument.
ASSIGNMENT_PATTERN = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)\s*=(?![=~])")

# XQL statement keywords and operators that appear as bare words. Function
# names are excluded structurally instead (any identifier followed by an
# opening bracket), which avoids maintaining an exhaustive list of XQL
# functions. This set only needs the words that are NOT followed by a bracket:
# stage commands, boolean/comparison operators, and ordering keywords.
XQL_KEYWORDS = {
    # stage commands
    "alter", "arrayexpand", "bin", "call", "comp", "config", "dataset",
    "dedup", "fields", "filter", "fillnull", "iploc", "join", "limit",
    "replacenull", "sort", "tabulate", "target", "timeframe", "transaction",
    "union", "view", "window", "model",
    # boolean / comparison / set operators
    "and", "or", "not", "in", "contains", "like", "between", "incidr", "is",
    "null", "true", "false",
    # clause and ordering keywords
    "as", "asc", "by", "desc", "else", "if", "then", "type", "append",
    "conflict_strategy", "inner", "left", "right", "outer", "full",
    "nullsfirst", "nullslast",
}

# An identifier whose root segment has no lowercase letter is a constant or
# enum reference, not a dataset column. This catches the XDM_CONST namespace
# and bare enum literals (OUTCOME_SUCCESS, TRUE, ...) without enumerating them.
CONSTANT_ROOT_PATTERN = re.compile(r"[a-z]")


class ModelingRuleImporter:
    """Import data model rules from raw XIF text into a pack."""

    def __init__(self, packs_dir: Path):
        """Initialise the importer.

        Args:
            packs_dir: Path to the Packs directory.
        """
        self.packs_dir = packs_dir

    def import_from_xif(
        self,
        xif_content: str,
        pack_name: str,
        name: str | None = None,
        minimal_schema: bool = False,
    ) -> dict:
        """Import a data model rule from XIF text.

        Args:
            xif_content: Raw XIF rule text.
            pack_name: Target pack name.
            name: Base name for the rule, or None to derive one from the
                dataset. The 'ModelingRule' suffix is appended automatically.
            minimal_schema: Emit only the raw log column instead of inferring
                columns from the rule body.

        Returns:
            Result dictionary describing the package that was written.

        Raises:
            ValueError: If the input is not a usable modelling rule, or the
                target pack is missing or unsafe to write to.
        """
        xif = self._normalise_line_endings(xif_content)

        if not xif.strip():
            raise ValueError("No XIF content provided")

        if not MODEL_HEADER_PATTERN.search(xif):
            raise ValueError(
                'Input does not look like a data model rule: no [MODEL: dataset="..."] '
                "header found. Copy the rule text from the tenant rule editor, "
                "including its header line."
            )

        datasets = self.extract_datasets(xif)
        if not datasets:
            raise ValueError(
                "No dataset found in the [MODEL:] header. Expected a header of the "
                'form [MODEL: dataset="vendor_product_raw"].'
            )

        pack_path = self.packs_dir / pack_name
        if not pack_path.exists():
            raise ValueError(f"Pack not found: {pack_name}")

        rules_dir = pack_path / "ModelingRules"
        if rules_dir.is_symlink():
            raise ValueError(
                "ModelingRules directory is a symlink; refusing to write "
                "through it to prevent path escape"
            )

        resolved_stem, display_name = self._derive_names(pack_name, datasets, name)
        self._validate_stem(resolved_stem)

        package_dir = rules_dir / resolved_stem
        self._assert_within(package_dir, pack_path)
        if package_dir.is_symlink():
            raise ValueError(
                f"Package directory '{resolved_stem}' is a symlink; refusing to "
                "write through it to prevent path escape"
            )

        if minimal_schema:
            columns = {dataset: [RAW_LOG_COLUMN] for dataset in datasets}
        else:
            inferred = self.infer_columns(xif)
            columns = {dataset: list(inferred) for dataset in datasets}

        package_dir.mkdir(parents=True, exist_ok=True)

        files = []
        files.append(
            self._write(
                package_dir,
                f"{resolved_stem}.yml",
                self._build_yaml(resolved_stem, display_name, datasets),
                pack_path,
            )
        )
        files.append(
            self._write(
                package_dir, f"{resolved_stem}.xif", self._build_xif(xif), pack_path
            )
        )
        files.append(
            self._write(
                package_dir,
                f"{resolved_stem}_schema.json",
                self._build_schema(columns),
                pack_path,
            )
        )

        warnings = []
        if not minimal_schema:
            for dataset, cols in columns.items():
                inferred_only = [c for c in cols if c != RAW_LOG_COLUMN]
                if inferred_only:
                    warnings.append(
                        f"{dataset}: inferred column(s) {', '.join(inferred_only)} "
                        f"as type '{DEFAULT_COLUMN_TYPE}' - review types before upload"
                    )
        if len(datasets) > 1:
            warnings.append(
                f"XIF declares {len(datasets)} datasets ({', '.join(datasets)}); "
                "all are declared in the schema as MR107 requires"
            )

        # The rule is written regardless (import is for round-tripping), but
        # these fields fail validation and never compile on the tenant.
        for finding in scan_unmappable_fields(xif):
            if finding["assignment"]:
                warnings.append(
                    f"line {finding['line']}: '{finding['field']}' is a "
                    f"platform-derived XDM field and cannot be a mapping target - "
                    f"validation will fail until the assignment is removed"
                )
            else:
                warnings.append(
                    f"line {finding['line']}: '{finding['field']}' is a "
                    f"platform-derived XDM field that a data model rule cannot "
                    f"populate - confirm this occurrence is intentional"
                )

        return {
            "stem": resolved_stem,
            "package_dir": str(package_dir),
            "datasets": datasets,
            "columns": columns,
            "files": files,
            "warnings": warnings,
        }

    def extract_datasets(self, xif: str) -> list[str]:
        """Return the datasets declared in the XIF, ordered and deduplicated.

        Uses the same expression as demisto-sdk so the result matches what
        validator MR107 will compute against the schema keys.
        """
        seen = []
        for match in SDK_DATASET_PATTERN.findall(xif):
            dataset = match.strip('"')
            if dataset and dataset not in seen:
                seen.append(dataset)
        return seen

    def infer_columns(self, xif: str) -> list[str]:
        """Infer the raw dataset columns the rule reads from.

        A column is an identifier the rule reads but never assigns. Names
        assigned earlier in the rule are intermediate values, not dataset
        columns, and XDM paths are mapping targets rather than sources.
        Function names are excluded structurally by ignoring any identifier
        followed by an opening bracket.

        The raw log column is always included.
        """
        body = self._strip_noise(xif)

        assigned = {
            name for name in ASSIGNMENT_PATTERN.findall(body)
        }

        referenced = []
        for match in IDENTIFIER_PATTERN.finditer(body):
            name = match.group(0)
            following = body[match.end():match.end() + 1]
            if following == "(":
                continue
            if name.lower() in XQL_KEYWORDS:
                continue
            if name.startswith("xdm."):
                continue
            if name in assigned:
                continue
            if name in referenced:
                continue
            referenced.append(name)

        # A dotted name that is not an XDM path is a nested reference; the
        # dataset column is its root.
        columns = []
        for name in referenced:
            root = name.split(".")[0]
            if not root or root in columns or root in assigned:
                continue
            # Skip constant / enum references (XDM_CONST, OUTCOME_SUCCESS, ...):
            # a real dataset column has at least one lowercase letter.
            if not CONSTANT_ROOT_PATTERN.search(root):
                continue
            columns.append(root)

        if RAW_LOG_COLUMN in columns:
            columns.remove(RAW_LOG_COLUMN)
        columns.insert(0, RAW_LOG_COLUMN)
        return columns

    def _strip_noise(self, xif: str) -> str:
        """Remove comments, string literals, and MODEL headers from the body.

        String literals are removed rather than blanked so that quoted values
        are never mistaken for column names.
        """
        body = COMMENT_PATTERN.sub(" ", xif)
        body = STRING_LITERAL_PATTERN.sub(" ", body)
        body = re.sub(r"\[[^\]]*\]", " ", body)
        return body

    def _derive_names(
        self, pack_name: str, datasets: list[str], name: str | None
    ) -> tuple[str, str]:
        """Derive the package stem and the display name for the rule.

        Modelling rules are conventionally named per dataset, not per pack, so
        a pack that ships many rules gets a distinct, meaningful name for each.
        The default base is the first dataset with any trailing ``_raw``
        dropped; an explicit ``name`` overrides it. The pack name is only a
        fallback when neither yields a usable token.

        Returns a ``(stem, display_name)`` pair, e.g.
        ``("CloudflareAccountAuditModelingRule",
        "Cloudflare Account Audit Modeling Rule")``. The stem satisfies MR108's
        id suffix and the display name satisfies its name suffix.
        """
        if name:
            tokens = self._tokenise(self._strip_rule_suffix(name))
        else:
            tokens = self._tokenise(self._strip_raw(datasets[0]))

        if not tokens:
            tokens = self._tokenise(pack_name)
        if not tokens:
            tokens = ["dataset"]

        capitalised = [t[:1].upper() + t[1:] for t in tokens]
        stem = "".join(capitalised) + MODELING_RULE_ID_SUFFIX
        display_name = " ".join(capitalised) + f" {MODELING_RULE_NAME_SUFFIX}"
        return stem, display_name

    def _tokenise(self, value: str) -> list[str]:
        """Split a name into lowercase word tokens.

        Breaks on non-alphanumeric separators and on camelCase boundaries, so
        both ``cloudflare_account_audit`` and ``CloudflareAccountAudit`` yield
        ``["cloudflare", "account", "audit"]``.
        """
        tokens = []
        for chunk in re.split(r"[^A-Za-z0-9]+", value):
            if not chunk:
                continue
            for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+|[0-9]+", chunk):
                tokens.append(part.lower())
        return tokens

    def _strip_raw(self, dataset: str) -> str:
        """Drop a trailing ``_raw`` suffix from a dataset name."""
        return dataset[:-4] if dataset.endswith("_raw") else dataset

    def _strip_rule_suffix(self, name: str) -> str:
        """Drop a trailing ModelingRule / Modeling Rule suffix if the user
        included one, so it is not doubled when the suffix is re-appended."""
        collapsed = re.sub(r"[^a-z0-9]", "", name.lower())
        if collapsed.endswith("modelingrule") or collapsed.endswith("modelingrules"):
            # Remove the last occurrence of the words from the original string.
            return re.sub(
                r"[\s_-]*modeling[\s_-]*rules?\s*$", "", name, flags=re.IGNORECASE
            )
        return name

    def _validate_stem(self, stem: str) -> None:
        """Reject a stem that is unsafe as a path segment or fails MR108."""
        if not stem:
            raise ValueError("Package stem is empty")
        if stem in (".", ".."):
            raise ValueError(f"Package stem is a path traversal segment: {stem!r}")
        if "/" in stem or "\\" in stem:
            raise ValueError(f"Package stem contains a path separator: {stem!r}")
        if Path(stem).is_absolute():
            raise ValueError(f"Package stem is an absolute path: {stem!r}")
        if not stem.endswith(MODELING_RULE_ID_SUFFIX):
            raise ValueError(
                f"Package stem '{stem}' must end with '{MODELING_RULE_ID_SUFFIX}' "
                f"(demisto-sdk validator MR108)"
            )

    def _assert_within(self, candidate: Path, root: Path) -> None:
        """Raise if a resolved path escapes the pack directory."""
        try:
            candidate.resolve().relative_to(root.resolve())
        except ValueError:
            raise ValueError(
                f"Path '{candidate}' resolves outside the pack directory "
                f"'{root}'; refusing to write"
            )

    def _write(self, package_dir: Path, filename: str, content: str, pack_path: Path) -> dict:
        """Write one package file, guarding against symlink and path escape."""
        file_path = package_dir / filename
        self._assert_within(file_path, pack_path)
        if file_path.is_symlink():
            raise ValueError(
                f"Pack file '{filename}' is a symlink; refusing to write "
                "through it to prevent path escape"
            )
        overwritten = file_path.exists()
        file_path.write_text(content, encoding="utf-8")
        return {
            "filename": filename,
            "path": str(file_path),
            "overwritten": overwritten,
        }

    def _build_yaml(self, stem: str, display_name: str, datasets: list[str]) -> str:
        """Build the rule YAML.

        The rules and schema keys must be empty strings (validator MR101); the
        sidecars are located by filename stem, not by these values. tags is a
        string for modelling rules, unlike parsing rules where it is a list.
        """
        data = {
            "id": stem,
            "name": display_name,
            "fromversion": DEFAULT_FROM_VERSION,
            "tags": datasets[0],
            "rules": "",
            "schema": "",
        }
        return yaml.dump(
            data, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    def _build_xif(self, xif: str) -> str:
        """Return the rule text with a single trailing newline."""
        return xif.rstrip("\n") + "\n"

    def _build_schema(self, columns: dict[str, list[str]]) -> str:
        """Build the schema JSON.

        One top-level key per dataset declared in the XIF, which is what
        validator MR107 compares.
        """
        schema = {
            dataset: {
                column: {"type": DEFAULT_COLUMN_TYPE, "is_array": False}
                for column in cols
            }
            for dataset, cols in columns.items()
        }
        return json.dumps(schema, indent=4) + "\n"

    def _normalise_line_endings(self, value: str) -> str:
        """Normalise CRLF and CR to LF.

        Console paste frequently carries Windows line endings.
        """
        return value.replace("\r\n", "\n").replace("\r", "\n")
