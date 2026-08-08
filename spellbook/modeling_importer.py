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

import yaml

from .rule_importer import RuleImporterBase
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

# The same, interleaved with brackets so a scan can tell an assignment from a
# comparison by depth: XQL uses '=' for both, and only a top-level one assigns.
ASSIGNMENT_OR_BRACKET_PATTERN = re.compile(
    r"([()\[\]{}])|([A-Za-z_][A-Za-z0-9_.]*)\s*=(?![=~])"
)

# A column whose name collides with an XQL operator is written in backticks,
# which is the only way the rule can read it (`in`, `out`, `filter`).
BACKTICK_IDENTIFIER_PATTERN = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]*)`")

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


def extract_datasets(xif: str) -> list[str]:
    """Return the datasets declared in an XIF, ordered and deduplicated.

    Module-level so the validator can compare a schema's keys against the
    rule's datasets without building an importer. Keeping one implementation
    matters more than the convenience: this is the expression MR107 uses, so
    the importer that WRITES a schema and the check that READS one have to
    agree, or spellbook would reject its own output.
    """
    seen = []
    for match in SDK_DATASET_PATTERN.findall(xif):
        dataset = match.strip('"')
        if dataset and dataset not in seen:
            seen.append(dataset)
    return seen


class ModelingRuleImporter(RuleImporterBase):
    """Import data model rules from raw XIF text into a pack."""

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
        self._validate_stem(resolved_stem, MODELING_RULE_ID_SUFFIX, "MR108")

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
                self._build_yaml(resolved_stem, display_name, pack_name),
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
                    # Naming the count and the completeness question, not just
                    # the types: a reader told to "review types" checks the
                    # types and does not think to check whether the SET is
                    # right, and a column the rule reads but the schema omits
                    # fails the install with an opaque error naming no field.
                    warnings.append(
                        f"{dataset}: inferred {len(inferred_only)} column(s) as "
                        f"type '{DEFAULT_COLUMN_TYPE}' - check both the types "
                        f"AND that no column the rule reads is missing: "
                        f"{', '.join(inferred_only)}"
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
        return extract_datasets(xif)

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

        assigned = self._assigned_names(body)

        # A backtick-quoted identifier is explicitly a column, which is how a
        # rule reads one whose name collides with an operator (`in`). Without
        # this it is filtered out as a keyword and the schema omits it.
        escaped = set(BACKTICK_IDENTIFIER_PATTERN.findall(body))

        referenced = []
        for match in IDENTIFIER_PATTERN.finditer(body):
            name = match.group(0)
            following = body[match.end():match.end() + 1]
            if following == "(":
                continue
            if name.lower() in XQL_KEYWORDS and name not in escaped:
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

    def _assigned_names(self, body: str) -> set[str]:
        """Return the names the rule assigns, as opposed to the ones it reads.

        XQL spells assignment and equality the same way, so `=` alone does not
        identify an assignment. Inside a call it is a comparison, and the
        identifier beside it is being READ:

            tmp_outcome = if(fg_status = "success", 1, act = "deny", 2)

        assigns tmp_outcome and reads fg_status and act. Treating all three as
        assigned dropped them from the schema, and a MODEL rule is validated
        statically against that schema, so a column the rule reads but the
        schema omits fails the install. Only a `name =` at bracket depth zero
        is an assignment. This shape is what per-record classification looks
        like, so it is the common case rather than an edge one.
        """
        assigned = set()
        depth = 0
        for match in ASSIGNMENT_OR_BRACKET_PATTERN.finditer(body):
            bracket, name = match.group(1), match.group(2)
            if bracket:
                depth = max(0, depth + (1 if bracket in "([{" else -1))
            elif depth == 0:
                assigned.add(name)
        return assigned

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

        An explicit ``name`` keeps the casing it was given. Tokenising lowers
        every token, so an acronym is unrecoverable: ``HuaweiNE`` came back as
        ``Huawei Ne`` and ``CiscoIOSXR`` as ``Cisco Iosxr``, which then had to
        be hand-edited. A dataset is lowercase to begin with, so it is still
        title-cased.
        """
        if name:
            explicit = self._strip_rule_suffix(name).strip()
            if explicit:
                stem = re.sub(r"[^A-Za-z0-9]", "", explicit) + MODELING_RULE_ID_SUFFIX
                return stem, f"{explicit} {MODELING_RULE_NAME_SUFFIX}"

        tokens = self._tokenise(self._strip_raw(datasets[0]))

        if not tokens:
            tokens = self._tokenise(pack_name)
        if not tokens:
            tokens = ["dataset"]

        capitalised = [t[:1].upper() + t[1:] for t in tokens]
        stem = "".join(capitalised) + MODELING_RULE_ID_SUFFIX
        display_name = " ".join(capitalised) + f" {MODELING_RULE_NAME_SUFFIX}"
        return stem, display_name

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

    def _build_yaml(self, stem: str, display_name: str, pack_name: str) -> str:
        """Build the rule YAML.

        The rules and schema keys must be empty strings (validator MR101); the
        sidecars are located by filename stem, not by these values. tags is a
        string for modelling rules, unlike parsing rules where it is a list.

        tags carries the pack name, matching what the SamplePack template
        emits and what most tagged rules in demisto/content do. Nothing reads
        it: the SDK does not model the field on the ModelingRule object and no
        validator references it, and half of official content leaves it empty.
        It was previously the dataset name, a value no official rule uses.
        """
        data = {
            "id": stem,
            "name": display_name,
            "fromversion": DEFAULT_FROM_VERSION,
            "tags": pack_name,
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
