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

from . import HOUSE_FROM_VERSION

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

DEFAULT_FROM_VERSION = HOUSE_FROM_VERSION

# Read from a sibling rule's YAML by expression rather than by parsing it: the
# collision check has to work against a pack someone is midway through editing,
# where a neighbouring YAML may not parse yet.
FROMVERSION_PATTERN = re.compile(r"^fromversion:\s*[\"']?([0-9][0-9.]*)", re.M)

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

# A bareword `= true` / `= false` comparison proves the column is boolean. The
# query parser REJECTS that comparison against a string column (ERR-014), so a
# rule that compiled on a tenant carries the type in its own text. This is the
# only type signal the rule body entails rather than merely suggests: measured
# against the shipped, hand-corrected packs it was right 13 times out of 13,
# while to_integer() on a column predicted 'int' only 16 times in 27.
#
# The lookbehind is load-bearing, not tidiness. Without it `tmp_is_login = true`
# also matches its own trailing `in`, and `in` is a genuine backticked column on
# CEF sources - declared string - so the wrong type would be written to a real
# column. The optional backticks admit the escaped form the same way
# BACKTICK_IDENTIFIER_PATTERN does.
BAREWORD_BOOL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])`?([A-Za-z_][A-Za-z0-9_]*)`?\s*=\s*(?:true|false)\b",
    re.IGNORECASE,
)

# A numeric cast applied directly to a column. Requiring the argument to be the
# entire call body excludes the placeholder form to_integer(0) and the wrapped
# form to_integer(coalesce(...)), where the cast says nothing about any one
# column. Unlike the boolean signal this is only a hint: the same syntax covers
# columns the tenant declares int, float and string, so it names the column in a
# warning and never sets a type.
NUMERIC_CAST_PATTERN = re.compile(
    r"\b(to_integer|to_float|to_number)\s*\(\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*\)"
)


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
        from_version: str = DEFAULT_FROM_VERSION,
    ) -> dict:
        """Import a data model rule from XIF text.

        Args:
            xif_content: Raw XIF rule text.
            pack_name: Target pack name.
            name: Base name for the rule, or None to derive one from the
                dataset. The 'ModelingRule' suffix is appended automatically.
            minimal_schema: Emit only the raw log column instead of inferring
                columns from the rule body.
            from_version: Platform version the rule declares. Sibling rules in
                one pack must not share it, or only one of them activates.

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

        booleans: list[str] = []
        numeric_casts: dict[str, list[str]] = {}
        nothing_inferred = False

        if minimal_schema:
            columns = {dataset: [RAW_LOG_COLUMN] for dataset in datasets}
        else:
            inferred = self.infer_columns(xif)
            if not inferred:
                # A rule that only assigns literals reads no column at all. An
                # empty dataset object parses, but it maps nothing, so fall back
                # to the raw log column and say so rather than write a schema
                # that cannot match a record.
                inferred = [RAW_LOG_COLUMN]
                nothing_inferred = True
            else:
                booleans = self.infer_boolean_columns(xif, inferred)
                numeric_casts = self.find_numeric_casts(xif, inferred)
            columns = {dataset: list(inferred) for dataset in datasets}

        types = {
            dataset: {
                column: "boolean" if column in booleans else DEFAULT_COLUMN_TYPE
                for column in cols
            }
            for dataset, cols in columns.items()
        }

        package_dir.mkdir(parents=True, exist_ok=True)

        files = []
        files.append(
            self._write(
                package_dir,
                f"{resolved_stem}.yml",
                self._build_yaml(resolved_stem, display_name, pack_name, from_version),
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
                self._build_schema(columns, types),
                pack_path,
            )
        )

        warnings = []
        for collision in self.find_activation_collisions(
            rules_dir, resolved_stem, from_version
        ):
            warnings.append(
                f"{pack_name} already has {collision} at fromversion "
                f"{from_version}. Two modelling rule directories at the same "
                f"fromversion cannot both activate - one wins and the other "
                f"models nothing. Add this dataset as another "
                f"[MODEL: dataset=...] block in the existing rule, or give this "
                f"one a distinct --fromversion"
            )
        if nothing_inferred:
            warnings.append(
                f"the rule reads no dataset column, so the schema declares only "
                f"'{RAW_LOG_COLUMN}' - confirm that is what the source populates"
            )
        if not minimal_schema and not nothing_inferred:
            for dataset, cols in columns.items():
                inferred_only = [c for c in cols if c != RAW_LOG_COLUMN]
                if inferred_only:
                    # Naming the count and the completeness question, not just
                    # the types: a reader told to "review types" checks the
                    # types and does not think to check whether the SET is
                    # right, and a column the rule reads but the schema omits
                    # fails the install with an opaque error naming no field.
                    # Columns typed below stay on this list for the same reason:
                    # confidence in one column's TYPE says nothing about whether
                    # the SET is complete.
                    warnings.append(
                        f"{dataset}: inferred {len(inferred_only)} column(s) - "
                        f"check both the types AND that no column the rule reads "
                        f"is missing: {', '.join(inferred_only)}"
                    )
                cast_hits = [c for c in cols if c in numeric_casts]
                if cast_hits:
                    detail = ", ".join(
                        f"{c} ({'/'.join(numeric_casts[c])})" for c in cast_hits
                    )
                    warnings.append(
                        f"{dataset}: {len(cast_hits)} column(s) are passed to a "
                        f"numeric cast in the rule and are likely 'int' or "
                        f"'float' rather than '{DEFAULT_COLUMN_TYPE}' - confirm "
                        f"against real rows: {detail}"
                    )
                typed = [c for c in cols if c in booleans]
                if typed:
                    warnings.append(
                        f"{dataset}: {len(typed)} column(s) typed 'boolean' from "
                        f"a bareword true/false comparison, which the query "
                        f"parser rejects against a string column: "
                        f"{', '.join(typed)}"
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
                    f"line {finding['line']}: '{finding['field']}' is not part "
                    f"of the data model a modelling rule maps to and cannot be a "
                    f"mapping target - validation will fail until the "
                    f"assignment is removed"
                )
            else:
                warnings.append(
                    f"line {finding['line']}: '{finding['field']}' is an XDM "
                    f"field a data model rule cannot populate - confirm this "
                    f"occurrence is intentional"
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

        The raw log column is included only when the rule actually reads it.
        It used to be injected unconditionally, which was wrong for every
        collector-ingested source: those datasets store the event parsed into
        top-level columns and leave _raw_log null, so the schema declared a
        column that is never populated and that the rule never reads. None of
        the shipped API packs declares it. Nothing special is needed to find it
        when the rule DOES read it - it is not an XQL keyword and it has
        lowercase letters, so ordinary inference already yields it.
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

        # Conventionally first when the rule reads it, so a schema for a raw
        # text source still opens on the column that carries the event.
        if RAW_LOG_COLUMN in columns:
            columns.remove(RAW_LOG_COLUMN)
            columns.insert(0, RAW_LOG_COLUMN)
        return columns

    def infer_boolean_columns(self, xif: str, columns: list[str]) -> list[str]:
        """Return the columns the rule proves are boolean.

        Restricted to names already established as columns by ``infer_columns``,
        so the type can only ever land on something the dataflow pass already
        accepted as read-but-never-assigned. That containment is what makes the
        three ERR-014 carve-outs fall out of existing machinery rather than
        needing their own cases:

        - ``col = "true"`` never matches, because _strip_noise deletes string
          literals before the scan.
        - ``to_boolean(col) = true`` never matches, because no bare identifier
          precedes the ``=``.
        - ``alter col = true`` is an assignment at bracket depth zero, so
          _assigned_names has already excluded it from ``columns``. Stage
          parameters (``append = true``) are XQL keywords and excluded too.

        The real comparisons all sit inside ``if(...)`` at depth above zero,
        which is exactly where _assigned_names treats a name as read.
        """
        allowed = set(columns)
        found = []
        for match in BAREWORD_BOOL_PATTERN.finditer(self._strip_noise(xif)):
            name = match.group(1)
            if name in allowed and name not in found:
                found.append(name)
        return found

    def find_numeric_casts(self, xif: str, columns: list[str]) -> dict[str, list[str]]:
        """Return columns passed to a numeric cast, mapped to the casts used.

        Advisory only. Against the shipped packs the same syntax covers columns
        the tenant declares int (16), string (6) and float (5), and no gate
        computable from the rule text separates them: a CEF rule that never
        mentions _raw_log still casts two columns the tenant declares float.
        Writing a type on 59% odds risks an opaque install failure, whereas the
        'string' default is recoverable at query time - so this names the
        columns for the author and leaves the type alone.
        """
        allowed = set(columns)
        found: dict[str, list[str]] = {}
        for match in NUMERIC_CAST_PATTERN.finditer(self._strip_noise(xif)):
            function, name = match.group(1), match.group(2)
            if name not in allowed or name == RAW_LOG_COLUMN:
                continue
            casts = found.setdefault(name, [])
            if function not in casts:
                casts.append(function)
        return found

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

    def find_activation_collisions(
        self, rules_dir, resolved_stem: str, from_version: str
    ) -> list[str]:
        """Return sibling rule directories that already claim this version.

        Two modelling rule directories in one pack declaring the same
        fromversion cannot both activate: the tenant picks one and the rest
        install, bind to their datasets and model nothing. Shipped content uses
        sibling directories only as version variants, giving each a distinct
        fromversion, which is why this compares versions rather than counting
        directories.

        Saying it here rather than only at upload matters because this is the
        moment the author can still fold the new dataset into the existing
        rule's .xif, before a pack is built around the broken shape.
        """
        if not rules_dir.is_dir():
            return []

        collisions = []
        for package in sorted(rules_dir.iterdir()):
            # Rewriting the rule's own directory is not a collision.
            if not package.is_dir() or package.name == resolved_stem:
                continue
            for yml_path in sorted(package.glob("*.yml")):
                try:
                    text = yml_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                match = FROMVERSION_PATTERN.search(text)
                if match and match.group(1) == from_version:
                    collisions.append(package.name)
                break
        return collisions

    def _build_yaml(
        self,
        stem: str,
        display_name: str,
        pack_name: str,
        from_version: str = DEFAULT_FROM_VERSION,
    ) -> str:
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
            "fromversion": from_version,
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

    def _build_schema(
        self, columns: dict[str, list[str]], types: dict[str, dict[str, str]]
    ) -> str:
        """Build the schema JSON.

        One top-level key per dataset declared in the XIF, which is what
        validator MR107 compares. Every type falls back to the default, so a
        column the type pass said nothing about is still declared.
        """
        schema = {
            dataset: {
                column: {
                    "type": types.get(dataset, {}).get(column, DEFAULT_COLUMN_TYPE),
                    "is_array": False,
                }
                for column in cols
            }
            for dataset, cols in columns.items()
        }
        return json.dumps(schema, indent=4) + "\n"
