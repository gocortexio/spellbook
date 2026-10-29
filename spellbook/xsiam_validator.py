# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
XSIAM Validator Module

Provides additional validation rules that catch XSIAM-specific issues
not detected by demisto-sdk. These rules are based on actual upload
failures encountered when pushing content to XSIAM.
"""

import configparser
import json
import re
from pathlib import Path

from dataclasses import dataclass

import yaml

from .modeling_importer import (
    SCHEMA_FILE_VALID_ATTRIBUTES_TYPE,
    extract_datasets,
)
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

# Fields the Cortex Platform stores and acts on for a correlation rule, but
# which demisto-sdk's StrictCorrelationRule does not declare: is_enabled
# decides whether the rule installs active, alert_domain picks the domain,
# timezone drives the crontab. They are kept, and not reported.
#
# demisto/content's CI does reject them. It applies the strict model as ST110,
# an error a pack cannot ignore, and none of the correlation rules merged there
# carries one; it rejects a list suppression_fields for the same reason.
# An interim build failed validate on them. The estate's decision (2026-10-22)
# is that tenant behaviour matters more than that store requirement, so they
# are exempt again - knowingly, not as the false positive an earlier version
# of this note took them for. simple_schedule is exempt here only because
# invalid_simple_schedule reports it with the platform reason.
PLATFORM_CORRELATION_FIELDS = {
    "action",
    "alert_domain",
    "alert_type",
    "is_enabled",
    "timezone",
    "lookup_mapping",
    "simple_schedule",
}

# The strict model types suppression_fields as a string; the platform stores
# and exports an array. Exempt by the same decision.
LIST_TOLERANT_FIELDS = {"suppression_fields"}

# demisto-sdk's PlatformSupportedModules: the only values `supportedModules`
# may hold. Licence codes (C1, X1, ENT_PLUS, ...) are not among them, and
# BA131 fails an item declaring one. test_sdk_contract keeps this equal to the
# pinned SDK's enum.
SUPPORTED_MODULES = frozenset({
    "agentix",
    "asm",
    "cloud",
    "cloud_appsec",
    "cloud_posture",
    "cloud_runtime_security",
    "data_security",
    "edr",
    "email_security",
    "exposure_management",
    "tim",
    "xsiam",
    "xti",
})

# Content directories whose YAML items have a demisto-sdk strict model.
# Maps the directory to its model module, model name, and whether the items
# sit in package subdirectories. Spellbook's `demisto-sdk validate` run does
# not select ST110, which applies these models, so they are applied here.

# demisto-sdk's name for the pack attribution file. The SDK reads it as a
# flat List[str] of contributor names; any other shape is unreadable to it.
CONTRIBUTORS_FILENAME = "CONTRIBUTORS.json"

# The value the scaffold used to write into a trigger's playbook_id. A trigger
# carrying it binds to nothing, and nothing else in the chain says so.
TRIGGER_PLAYBOOK_PLACEHOLDER = "PLAYBOOK_ID_HERE"

# demisto-sdk locates a modelling rule's schema by the YAML stem, so the
# schema file is always the stem plus this suffix.
SCHEMA_FILENAME_SUFFIX = "_schema.json"

# Read from the rule YAML rather than parsed with the rest of the file: this
# check has to survive a YAML that fails to parse, because a pack whose rules
# collide is exactly the pack someone is midway through editing.
FROMVERSION_PATTERN = re.compile(
    r"""^﻿?["']?fromversion["']?:\s*["']?([0-9][0-9.]*)""", re.M
)

# Python and PowerShell content runs in the container its `dockerimage` names -
# at the root of a script, under `script:` in an integration. JavaScript runs in
# the server's own engine and takes none. This is demisto-sdk's DO104, checked
# here instead of selected there; pack_builder.SDK_DEFAULTS_CHECKED_NATIVELY
# records why.
CONTAINERLESS_SCRIPT_TYPES = {"javascript"}

# The image family to point an author at. DO104 fetched the newest tag from
# Docker Hub to name one in its message, and that fetch is what crashed, so the
# remediation names the tag list rather than a tag.
DOCKER_IMAGE_BY_TYPE = {
    "python": "demisto/python3",
    "powershell": "demisto/powershell",
}

# Keys only a prompt-backed script carries. One of these on a script that is not
# marked `isllm: true` is an author who forgot the flag, not one who forgot an
# image, and the two fixes are different.
PROMPT_SCRIPT_KEYS = {"userprompt", "systemprompt"}

# Datasets declared by an actual [MODEL:] header, as opposed to every
# "dataset =" in the file. extract_datasets deliberately mirrors demisto-sdk's
# loose expression so the schema-keys comparison matches MR107 exactly, but that
# expression also matches a dataset named in a COMMENT - and CiscoIOS names one
# in three comment lines while modelling a different dataset entirely. Using the
# loose set to assert "the .xif models X" reports a rule for prose about a
# dataset it deliberately does not model.
MODEL_HEADER_DATASET_PATTERN = re.compile(
    r"""^\s*\[\s*MODEL\s*:\s*dataset\s*=\s*["']?([A-Za-z_0-9]+)""",
    re.M | re.IGNORECASE,
)

# demisto-sdk's release-note grammar, mirrored for RN113, RN114 and RN115.
# Those validators run only on a pack git reports as MODIFIED, so spellbook's
# `validate -i` never runs them, yet demisto/content's CI fails a pull request
# updating a merged pack on any of them. Copied from the pinned SDK, and
# test_sdk_contract keeps each equal to it.
#
# RN_HEADER_BY_FILE_TYPE's values: the only valid first-level `####` headers.
RN_CONTENT_TYPE_HEADERS = frozenset({
    "Actions", "Agents", "Assets Modeling Rules", "Case Fields",
    "Case Layout Rules", "Case Layouts", "Classifiers",
    "Correlation Rules", "Dashboards", "Incident Fields", "Incident Types",
    "Indicator Fields", "Indicator Types", "Integrations", "Jobs", "Knowledge",
    "Layout Rules", "Layouts", "Lists", "Mappers", "Modeling Rules",
    "Modeling Rules Schema", "Modules", "Object Fields", "Object Types",
    "Objects", "Parsing Rules", "Playbooks", "PreProcess Rules", "Reports",
    "Scripts", "Skills", "Triggers Recommendations", "Widgets", "Wizards",
    "XDRC Templates", "XSIAM Dashboards", "XSIAM Reports",
})
# CONTENT_TYPE_SECTION_REGEX and CONTENT_ITEM_SECTION_REGEX.
RN_TYPE_SECTION = re.compile(
    r"^#### ([\w ]+)$\n([\w\W]*?)(?=^#### )|^#### ([\w ]+)$\n([\w\W]*)", re.M
)
RN_ITEM_SECTION = re.compile(
    r"^##### (.+)$\n([\w\W]*?)(?=^##### )|^##### (.+)$\n([\w\W]*)|"
    r"^- (?:New: )?$",
    re.M,
)
# PB_RELEASE_NOTES_FORMAT: sub-headers RN114 allows under Playbooks.
RN_PLAYBOOK_SUBHEADERS = frozenset({
    "This playbook addresses the following alerts:", "Playbook Stages:",
    "Requirements:", "Triage:", "Early Containment:", "Investigation:",
    "Containment:",
})
RN_NEW_ITEM_PREFIX = "New: "
# Valid first-level headers RN113 accepts but RN114 rejects as a content type:
# the SDK cannot map the header back to itself (Modeling Rules Schema has no
# content type; Case Layouts maps to CaseLayout, whose header is Layouts).
# test_sdk_contract recomputes this from the SDK.
RN114_REJECTED_HEADERS = frozenset({"Case Layouts", "Modeling Rules Schema"})

# Where RN114 finds the display name of each kind of item a release note can
# name: the folder, how its descriptors are laid out, the field path, and the
# fallback the SDK's parser uses when the name is empty (an item's id). A
# header for a kind not mapped here is not checked, rather than checked
# against a guess.
RN_DISPLAY_NAME_SOURCES = {
    "Integrations": ("Integrations", "package", ("display",), None),
    "Scripts": ("Scripts", "package", ("name",), ("commonfields", "id")),
    "Playbooks": ("Playbooks", "flat-yml", ("name",), ("id",)),
    "Correlation Rules": ("CorrelationRules", "flat-yml", ("name",), ("global_rule_id",)),
    "Modeling Rules": ("ModelingRules", "nested-yml", ("name",), ("id",)),
    "Parsing Rules": ("ParsingRules", "nested-yml", ("name",), ("id",)),
    "XSIAM Dashboards": ("XSIAMDashboards", "json", ("dashboards_data", 0, "name"), ("dashboards_data", 0, "global_id")),
    "XSIAM Reports": ("XSIAMReports", "json", ("templates_data", 0, "report_name"), ("templates_data", 0, "global_id")),
    "Triggers Recommendations": ("Triggers", "json", ("trigger_name",), ("trigger_id",)),
    "Incident Fields": ("IncidentFields", "json", ("name",), ("id",)),
    "Incident Types": ("IncidentTypes", "json", ("name",), ("id",)),
    "Layouts": ("Layouts", "json", ("name",), ("id",)),
    "Jobs": ("Jobs", "json", ("name",), ("id",)),
}

# How demisto-sdk decides a pack is deprecated, which skips RN113/RN114/RN115:
# not a metadata key, but a name ending "(Deprecated)" AND a description
# opening "Deprecated. Use X instead." or "Deprecated. No available
# replacement." (PACK_NAME_DEPRECATED_REGEX, DEPRECATED_DESC_REGEX and
# DEPRECATED_NO_REPLACE_DESC_REGEX; test_sdk_contract keeps them equal).
PACK_NAME_DEPRECATED = re.compile(r".* \(Deprecated\)")
PACK_DESC_DEPRECATED = (
    re.compile(r"Deprecated\.\s*(.*?No available replacement\.*?)"),
    re.compile(r"Deprecated\.\s*(.*?Use .*? instead\.*?)"),
)

# Pack folders that hold no content items. RN114 is skipped for a pack with no
# items of any kind, so these are left out when deciding whether it has any.
RN_NON_CONTENT_DIRS = {"ReleaseNotes", "doc_files", "doc_imgs", "test_data"}

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
    """Represents a validation issue found in content.

    Three fields carry the finding rather than one. Spellbook is driven mostly
    by an agent now, and a bare statement of what was seen leaves the reader to
    infer both why it matters and what to do - which is how a finding gets
    dismissed as noise, or "fixed" in a way that satisfies the check and not the
    reason for it.

    message      what is wrong, in one line
    consequence  what happens if it ships this way
    remediation  the concrete edit that resolves it

    consequence and remediation default to empty so every existing emission
    site stays valid; the renderer omits what is absent.
    """
    rule_name: str
    severity: str  # "error" or "warning"
    file_path: str
    message: str
    line_number: int | None = None
    consequence: str = ""
    remediation: str = ""

    def as_dict(self) -> dict:
        """Return the issue as a JSON-serialisable mapping.

        `rule_name` is the stable identifier: an agent keys on it rather than
        matching prose, which is free to change.
        """
        return {
            "rule_name": self.rule_name,
            "severity": self.severity,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "message": self.message,
            "consequence": self.consequence,
            "remediation": self.remediation,
        }


@dataclass
class ValidationRule:
    """Defines a validation rule for content checking."""
    name: str
    content_type: str  # ParsingRules, CorrelationRules, etc.
    file_pattern: str  # *.xif, *.yml, etc.
    pattern: str  # Regex pattern to detect issues
    message: str
    severity: str = "error"
    consequence: str = ""
    remediation: str = ""


def check_modeling_rule_activation(pack_path: Path) -> list[ValidationIssue]:
    """Check that sibling modelling rule directories can all activate.

    Several modelling rule directories in one pack is a legitimate and common
    layout, but only as VERSION VARIANTS of one rule: shipped content writes
    `OktaModelingRules`, `OktaModelingRules_1_3` and `OktaModelingRules_2_0`
    against the same dataset and lets the tenant pick the one matching its
    platform version. Exactly one activating is the intent there.

    Give two sibling directories the SAME `fromversion` and the tenant has no
    basis to choose. One activates; the others install, register against their
    datasets with deprecated=false, and model nothing. Nothing reports it -
    the pack validates, lints, unifies, uploads and reinstalls clean, and the
    only symptom is a dataset that stays empty. It cost a day of field time to
    find.

    The discriminator is the version, not the directory count. Across the 272
    packs in demisto/content that ship modelling rules, 51 use sibling
    directories and all 51 give every sibling a distinct `fromversion`; none
    shares one. So this rejects nothing that shipped content does.

    Spellbook can walk into this on its own: `summon datamodel` stamps every
    rule with the same DEFAULT_FROM_VERSION, so summoning a second rule into a
    pack produces the colliding shape by default.

    Module-level so `upload` can run it as a pre-flight, matching
    check_modeling_schemas.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        List of validation issues found.
    """
    rules_dir = pack_path / "ModelingRules"
    if not rules_dir.is_dir():
        return []

    packages = sorted(d for d in rules_dir.iterdir() if d.is_dir())
    if len(packages) < 2:
        return []

    by_version: dict[str, list[tuple[str, list[str]]]] = {}
    for package in packages:
        yml_path = next(iter(sorted(package.glob("*.yml"))), None)
        if yml_path is None:
            continue
        try:
            yml_text = yml_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        match = FROMVERSION_PATTERN.search(yml_text)
        # A rule with no fromversion at all is grouped under "" and still
        # collides with another that also declares none: the tenant is no
        # better able to choose between them.
        version = match.group(1) if match else ""

        datasets: list[str] = []
        for xif_path in sorted(package.glob("*.xif")):
            try:
                xif_text = xif_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for dataset in extract_datasets(xif_text):
                if dataset not in datasets:
                    datasets.append(dataset)

        by_version.setdefault(version, []).append((package.name, datasets))

    issues = []
    for version, colliding in sorted(by_version.items()):
        if len(colliding) < 2:
            continue
        listing = "; ".join(
            f"{name} -> {', '.join(datasets) if datasets else 'no dataset found'}"
            for name, datasets in colliding
        )
        named = (
            f"fromversion {version}" if version else "no fromversion declared"
        )
        issues.append(ValidationIssue(
            rule_name="modeling_rules_collide",
            severity="error",
            file_path=str(rules_dir.relative_to(pack_path.parent)),
            message=(
                f"{len(colliding)} modelling rule directories share {named}: "
                f"{listing}. Only one will activate on the tenant; the others "
                f"install, bind to their datasets and model nothing"
            ),
            consequence=(
                "only one activates on the tenant; the rest register against "
                "their datasets and model nothing, with no error at any stage"
            ),
            remediation=(
                "either give each a distinct fromversion (the version-variant "
                "layout shipped content uses), or model several datasets with "
                "several [MODEL: dataset=...] blocks in ONE .xif and one "
                "schema keyed by dataset"
            ),
        ))
    return issues


def check_modeling_schemas(pack_path: Path) -> list[ValidationIssue]:
    """Check every modelling rule's `_schema.json` is readable and coherent.

    Presence alone was checked before this. A schema that is present but
    unusable passed with exit 0 and then failed at upload as an unhandled
    traceback: malformed JSON raised JSONDecodeError, and a top-level array
    raised "'list' object has no attribute 'keys'". Neither named the pack,
    the file, or the line.

    The four things checked here are the ones a MODEL rule is validated
    against statically on the tenant, so getting any of them wrong means the
    rule maps nothing:

    - the file parses as JSON at all
    - its root is an object, keyed by dataset
    - those keys are datasets the rule's own .xif declares (MR107's rule,
      compared with MR107's own expression via extract_datasets)
    - each column carries a `type` from MR106's closed set and a boolean
      `is_array`

    Module-level rather than a method so `upload` can run the same check as a
    pre-flight and refuse with a sentence instead of a traceback.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        List of validation issues found.
    """
    rules_dir = pack_path / "ModelingRules"
    if not rules_dir.is_dir():
        return []

    issues: list[ValidationIssue] = []

    def fail(path: Path, message: str, remediation: str = "") -> ValidationIssue:
        return ValidationIssue(
            rule_name="modeling_schema_invalid",
            severity="error",
            file_path=str(path.relative_to(pack_path.parent)),
            message=message,
            consequence=(
                "a MODEL rule is validated against this schema statically on "
                "the tenant, so the rule maps nothing and the upload fails "
                "with an error naming no field"
            ),
            remediation=remediation or (
                "re-import the rule with `summon datamodel`, which regenerates "
                "the schema from the .xif"
            ),
        )

    for schema_path in sorted(rules_dir.rglob(f"*{SCHEMA_FILENAME_SUFFIX}")):
        # A directory of that name is reported by the file-set check as a
        # missing schema; reading it here would raise instead.
        if not schema_path.is_file():
            continue

        try:
            data = json.loads(schema_path.read_text(encoding="utf-8"))
        except OSError as error:
            issues.append(fail(
                schema_path,
                f"could not be read: {error}",
            ))
            continue
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            issues.append(fail(
                schema_path,
                f"is not valid JSON: {error}. Upload would fail on this with "
                f"an unhandled traceback naming no file",
            ))
            continue

        if not isinstance(data, dict):
            issues.append(fail(
                schema_path,
                f"root must be an object keyed by dataset, not "
                f"{type(data).__name__}",
            ))
            continue

        if not data:
            issues.append(fail(
                schema_path,
                "declares no dataset - the rule would map nothing",
            ))
            continue

        # MR107: the schema's keys are compared against the datasets the
        # sibling .xif declares. Skip silently when there is no .xif; the
        # file-set check already reports that as its own finding.
        stem = schema_path.name[: -len(SCHEMA_FILENAME_SUFFIX)]
        xif_path = schema_path.with_name(f"{stem}.xif")
        if xif_path.is_file():
            try:
                xif_text = xif_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                issues.append(fail(
                    xif_path,
                    f"could not be read: {error}",
                ))
            else:
                declared = set(extract_datasets(xif_text))
                if not declared:
                    issues.append(fail(
                        schema_path,
                        f"has a schema but {xif_path.name} declares no "
                        f"dataset the parser can find - the rule would map "
                        f"nothing",
                    ))
                else:
                    # MR107 is set EQUALITY, and only one direction was
                    # checked. The unchecked one is the direction the tool's
                    # own advice leads to: modeling_rules_collide tells authors
                    # to add another [MODEL: dataset=...] block to an existing
                    # .xif, and forgetting the matching schema entry then
                    # passed spellbook and failed the store.
                    undeclared = sorted(set(data) - declared)
                    if undeclared:
                        issues.append(fail(
                            schema_path,
                            f"declares dataset(s) {', '.join(undeclared)} "
                            f"that {xif_path.name} does not use (it declares "
                            f"{', '.join(sorted(declared))})",
                            remediation=(
                                "remove the unused dataset key, or add a "
                                "[MODEL: dataset=...] block for it to the .xif"
                            ),
                        ))

                    modelled = set(
                        MODEL_HEADER_DATASET_PATTERN.findall(xif_text)
                    )
                    unmodelled = sorted(modelled - set(data))
                    if unmodelled:
                        issues.append(fail(
                            schema_path,
                            f"{xif_path.name} models dataset(s) "
                            f"{', '.join(unmodelled)} but the schema declares "
                            f"no columns for them",
                            remediation=(
                                "add a top-level key per dataset, or re-import "
                                "with `summon datamodel`, which writes every "
                                "dataset the rule declares"
                            ),
                        ))

        for dataset, columns in data.items():
            if not isinstance(columns, dict):
                issues.append(fail(
                    schema_path,
                    f"dataset '{dataset}' must map to an object of columns, "
                    f"not {type(columns).__name__}",
                ))
                continue

            for column, attributes in columns.items():
                where = f"{dataset}.{column}"
                if not isinstance(attributes, dict):
                    issues.append(fail(
                        schema_path,
                        f"column '{where}' must be an object with 'type' and "
                        f"'is_array', not {type(attributes).__name__}",
                    ))
                    continue

                column_type = attributes.get("type")
                if column_type not in SCHEMA_FILE_VALID_ATTRIBUTES_TYPE:
                    valid = ", ".join(sorted(SCHEMA_FILE_VALID_ATTRIBUTES_TYPE))
                    issues.append(fail(
                        schema_path,
                        f"column '{where}' has type {column_type!r}; "
                        f"demisto-sdk accepts only {valid}",
                    ))

                if not isinstance(attributes.get("is_array"), bool):
                    issues.append(fail(
                        schema_path,
                        f"column '{where}' needs a boolean 'is_array', "
                        f"found {attributes.get('is_array')!r}",
                    ))

    return issues


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
            message="the INGEST directive carries a 'content_id' field",
            severity="error",
            consequence="the platform does not support it and rejects the rule",
            remediation="remove content_id from the [INGEST: ...] header"
        ),
        
        # Correlation Rules checks
        ValidationRule(
            name="invalid_simple_schedule",
            content_type="CorrelationRules",
            file_pattern="*.yml",
            # A quoted key, or one after a BOM, is the same key; the strict
            # check leaves simple_schedule to this rule, so it must see both.
            pattern=r"""^﻿?\s*["']?simple_schedule["']?\s*:""",
            message="the correlation rule carries a 'simple_schedule' field",
            severity="error",
            consequence=(
                "it is superseded by crontab/execution_mode/search_window, and "
                "leaving it in has been observed to fail the upload"
            ),
            remediation=(
                "remove simple_schedule and express the schedule with crontab, "
                "execution_mode and search_window"
            )
        ),
        ValidationRule(
            name="parentheses_in_correlation_name",
            content_type="CorrelationRules",
            file_pattern="*.yml",
            pattern=r'^\s*name\s*:\s*.*[\(\)]',
            message="the correlation rule name contains parentheses",
            severity="warning",
            consequence="parentheses in a rule name have caused platform issues",
            remediation="replace them with hyphens"
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

        issues.extend(self._check_rule_file_sets(pack_path))

        issues.extend(self._check_contributors(pack_path))

        issues.extend(self._check_trigger_placeholders(pack_path))

        issues.extend(self._check_pack_metadata_readable(pack_path))

        issues.extend(self._check_pack_categories(pack_path))

        issues.extend(self._check_supported_modules(pack_path))

        issues.extend(self._check_correlation_drilldown(pack_path))

        issues.extend(check_modeling_schemas(pack_path))

        issues.extend(check_modeling_rule_activation(pack_path))

        issues.extend(check_release_notes(pack_path))

        return issues

    def _check_correlation_drilldown(self, pack_path: Path) -> list[ValidationIssue]:
        """Check each correlation rule's drill-down has at least one stage.

        `investigation_query_link` is the query an analyst opens from the alert.
        A bare dataset read with no pipe stages is rejected by the platform, and
        the rejection fails the ENTIRE pack install with 101704 - an error that
        names no file, no field and no line. The console holds the real message
        ("Correlation drill-down query ... may not be empty") but it never
        reaches whoever pushed the pack.

        Isolated in the field on an otherwise byte-identical rule: only this
        field changed between a failed install and a successful one. It cost
        most of a day, and the day was spent on the wrong hypothesis, because
        the faulty field was copied unchanged into every probe and so was
        invisible to a bisect over the query itself.

        There is no legitimate bare form to protect: a drill-down with no stages
        returns the whole dataset unfiltered, which is useless to a responder
        even where it does install.

        Only a field that is present and non-empty is checked. Whether an absent
        drill-down is also rejected has not been established, and is not
        inferred from this evidence.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        rules_dir = pack_path / "CorrelationRules"
        if not rules_dir.is_dir():
            return []

        issues = []
        for yml_path in sorted(rules_dir.rglob("*.yml")):
            try:
                data = yaml.safe_load(yml_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                # A rule that does not parse is reported by the strict-model
                # check; do not duplicate it with a worse message.
                continue
            if not isinstance(data, dict):
                continue

            query = data.get("investigation_query_link")
            if not isinstance(query, str) or not query.strip():
                continue
            if "|" in query:
                continue

            issues.append(ValidationIssue(
                rule_name="correlation_drilldown_needs_stages",
                severity="error",
                file_path=str(yml_path.relative_to(pack_path.parent)),
                message=(
                    "investigation_query_link is a bare dataset read with no "
                    "pipe stages"
                ),
                consequence=(
                    "the platform rejects it and fails the ENTIRE pack install "
                    "with 101704, which names no file and no field; the console "
                    "reports it as \"Correlation drill-down query ... may not "
                    "be empty\""
                ),
                remediation=(
                    "add at least a filter binding the drill-down to the "
                    "alert's own entity, plus a fields stage, e.g. "
                    "`| filter <key> = \"$<key>\" | fields _time, ...`"
                ),
            ))
        return issues

    def _check_supported_modules(self, pack_path: Path) -> list[ValidationIssue]:
        """Check integrations declare module names in supportedModules.

        A licence code such as C1, X1 or ENT_PLUS is not a module.
        demisto-sdk's strict integration model types every supportedModules
        - the integration's, each configuration parameter's and each
        command's - as a list of module names, so demisto/content's CI fails
        a code in any of them (ST110), and BA131 fails one in the integration's
        own. It is checked here rather than BA131 selected, because BA131 also
        rejects the module set the SDK assumes for a rule item that declares
        none - a value the author never wrote; pack_builder records the
        measurement.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        issues = []
        for yml_path in content_descriptors(pack_path / "Integrations"):
            try:
                text = yml_path.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                # Unparseable YAML is demisto-sdk's to report.
                continue
            if not isinstance(data, dict):
                continue

            # (where, value, line, the codes that fail it)
            declarations = [(
                "supportedModules",
                data.get("supportedModules"),
                _root_key_line(text, "supportedModules"),
                "BA131 and ST110",
            )]
            configuration = data.get("configuration")
            for param in configuration if isinstance(configuration, list) else []:
                if isinstance(param, dict) and "supportedModules" in param:
                    declarations.append((
                        f"supportedModules of configuration parameter "
                        f"'{param.get('name', '?')}'",
                        param["supportedModules"],
                        None,
                        "ST110",
                    ))
            script = data.get("script")
            commands = script.get("commands") if isinstance(script, dict) else None
            for command in commands if isinstance(commands, list) else []:
                if isinstance(command, dict) and "supportedModules" in command:
                    declarations.append((
                        f"supportedModules of command '{command.get('name', '?')}'",
                        command["supportedModules"],
                        None,
                        "ST110",
                    ))

            for where, value, line, codes in declarations:
                if value is None:
                    continue
                if isinstance(value, list):
                    invalid = [
                        str(v) for v in value
                        if not (isinstance(v, str) and v in SUPPORTED_MODULES)
                    ]
                    if not invalid:
                        continue
                    message = (
                        f"{where} holds {', '.join(invalid)}, which "
                        f"{'is not a module name' if len(invalid) == 1 else 'are not module names'}"
                    )
                else:
                    message = f"{where} is '{value}', not a list of module names"
                issues.append(ValidationIssue(
                    rule_name="supported_modules_invalid",
                    severity="error",
                    file_path=str(yml_path.relative_to(pack_path.parent)),
                    line_number=line,
                    message=message,
                    consequence=(
                        f"demisto/content's CI accepts only demisto-sdk's "
                        f"module names there and fails the pull request "
                        f"({codes}); licence codes such as C1 or X1 are not "
                        f"modules, and no merged integration uses them"
                    ),
                    remediation=(
                        "replace them with module names - an XSIAM collector "
                        "takes [xsiam]; the valid modules are "
                        f"{', '.join(sorted(SUPPORTED_MODULES))}"
                    ),
                ))
        return issues

    def _check_pack_metadata_readable(self, pack_path: Path) -> list[ValidationIssue]:
        """Check pack_metadata.json exists and parses.

        This check is the one _check_pack_categories defers to. It did not
        exist: that method caught a parse error and returned [] with a comment
        saying the case was "reported by its own check", which was an assertion
        about a guarantee nobody had built. The result was that a pack whose
        metadata was not valid JSON passed validate with [PASS] - the gate
        reporting green on a pack the platform cannot install, and on a file
        every later stage reads.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        path = pack_path / "pack_metadata.json"
        relative = f"{pack_path.name}/pack_metadata.json"

        if not path.is_file():
            return [ValidationIssue(
                rule_name="pack_metadata_unreadable",
                severity="error",
                file_path=relative,
                message="no pack_metadata.json at the pack root",
                consequence=(
                    "the marketplace has no name, version or categories for "
                    "the pack, and every spellbook command that reads it falls "
                    "back to a stub"
                ),
                remediation=(
                    "create it, or re-scaffold the pack with `spellbook create`"
                ),
            )]

        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as error:
            return [ValidationIssue(
                rule_name="pack_metadata_unreadable",
                severity="error",
                file_path=relative,
                message=f"could not be read: {error}",
                consequence="every stage that reads the pack's metadata fails",
                remediation="fix the file's permissions or encoding",
            )]

        if not content.strip():
            return [ValidationIssue(
                rule_name="pack_metadata_unreadable",
                severity="error",
                file_path=relative,
                message="is empty",
                consequence=(
                    "an empty file parses as nothing, so the pack has no "
                    "version and builds to a zip named for a version it does "
                    "not have"
                ),
                remediation="restore the metadata, or re-scaffold the pack",
            )]

        try:
            data = json.loads(content)
        except json.JSONDecodeError as error:
            return [ValidationIssue(
                rule_name="pack_metadata_unreadable",
                severity="error",
                file_path=relative,
                message=f"is not valid JSON: {error}",
                consequence=(
                    "validate used to pass this, and build then emitted a zip "
                    "named for the wrong version; the platform cannot install "
                    "the pack either way"
                ),
                remediation="correct the JSON - a trailing comma is the usual cause",
            )]

        if not isinstance(data, dict):
            return [ValidationIssue(
                rule_name="pack_metadata_unreadable",
                severity="error",
                file_path=relative,
                message=f"must be a JSON object, not {type(data).__name__}",
                consequence="every consumer reads it as a mapping and fails",
                remediation="wrap the content in a single top-level object",
            )]

        return []

    def _check_pack_categories(self, pack_path: Path) -> list[ValidationIssue]:
        """Check the pack declares at least one marketplace category.

        The scaffold writes `"categories": []` deliberately: it is a required
        key and an empty list is the honest placeholder for a decision the
        author has not made yet. Leaving it empty is fine while building, and
        wrong the moment the pack is shipped - the marketplace files an
        uncategorised pack where nobody browsing will find it, and nothing in
        the upload path says so.

        So the scaffold keeps emitting it and this refuses it, which puts the
        complaint at the point the decision is actually being made rather than
        at the point it is being deferred.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        metadata_path = pack_path / "pack_metadata.json"
        if not metadata_path.is_file():
            return []

        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # Reported by _check_pack_metadata_readable, which runs first.
            # Do not duplicate it here with a worse message.
            return []

        if not isinstance(metadata, dict):
            return []

        categories = metadata.get("categories")
        if isinstance(categories, list) and categories:
            return []

        return [ValidationIssue(
            rule_name="empty_pack_categories",
            severity="error",
            file_path=f"{pack_path.name}/pack_metadata.json",
            message="categories is empty",
            consequence=(
                "the marketplace files the pack uncategorised, so nobody "
                "browsing the store finds it"
            ),
            remediation=(
                "set at least one category the store already lists, for "
                "example \"Network Security\", \"Analytics & SIEM\" or "
                "\"Forensics & Malware Analysis\". The scaffold writes an "
                "empty list deliberately, as a placeholder for this decision"
            ),
        )]

    def _check_trigger_placeholders(self, pack_path: Path) -> list[ValidationIssue]:
        """Check that no trigger still carries the scaffold's placeholder.

        A trigger is the only content-level thing binding an issue to a
        playbook; a correlation rule carries no field naming one. Leave the
        placeholder in and everything still installs, validates and runs when
        started by hand. The playbook is simply never started by anything, and
        the only way to notice is to wait for an issue that should have run it
        and see that it did not.

        Nothing else catches this. demisto-sdk ships TR100 and TR101 but its
        default_config.toml selects no TR codes, so neither runs, and no SDK
        validator cross-references playbook_id against the pack's playbooks.

        Only the literal placeholder is checked. An empty playbook_id is
        legitimate on a quick-action trigger, which binds to an automation
        instead, and deciding whether a real id names the right playbook is
        not something this can know.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        triggers_dir = pack_path / "Triggers"
        if not triggers_dir.is_dir():
            return []

        issues = []
        for path in sorted(triggers_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # Shape is demisto-sdk's business; only the placeholder here.
                continue

            if not isinstance(data, dict):
                continue

            if data.get("playbook_id") == TRIGGER_PLAYBOOK_PLACEHOLDER:
                issues.append(ValidationIssue(
                    rule_name="trigger_placeholder_playbook_id",
                    severity="error",
                    file_path=str(path.relative_to(pack_path.parent)),
                    message=(
                        f"playbook_id is still the placeholder "
                        f"'{TRIGGER_PLAYBOOK_PLACEHOLDER}'"
                    ),
                    consequence=(
                        "as written the trigger starts nothing, and nothing "
                        "else in the chain reports that"
                    ),
                    remediation=(
                        "set it to the id of the playbook this trigger should "
                        "start, or delete the trigger"
                    ),
                ))

        return issues

    def _check_contributors(self, pack_path: Path) -> list[ValidationIssue]:
        """Check that the pack carries a readable CONTRIBUTORS.json.

        The format is demisto-sdk's, not one of our own: a flat JSON array of
        contributor names. The SDK reads it as List[str]
        (content_graph/parsers/pack.py) and renders the names into the pack
        README, so any other shape - an object, nested records - is a file the
        marketplace cannot read.

        Requiring it is a house rule. Upstream treats the file as optional and
        many official packs ship none; a pack without attribution is not one
        we ship, so it is an error here. It is reported alongside every other
        finding rather than aborting the run, because stopping early would
        hide the rest of the pack's problems.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        path = pack_path / CONTRIBUTORS_FILENAME
        relative = f"{pack_path.name}/{CONTRIBUTORS_FILENAME}"

        if not path.is_file():
            return [ValidationIssue(
                rule_name="missing_contributors",
                severity="error",
                file_path=relative,
                message="no CONTRIBUTORS.json at the pack root",
                consequence=(
                    "validate fails and the pack ships with no attribution; "
                    "this is a house rule, upstream treats the file as optional"
                ),
                remediation=(
                    'create it as a flat JSON array of names, e.g. '
                    '["Simon Sigre"]'
                ),
            )]

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            return [ValidationIssue(
                rule_name="invalid_contributors",
                severity="error",
                file_path=relative,
                message=f"is not valid JSON: {error}",
                consequence=(
                    "demisto-sdk cannot read the pack's attribution, and the "
                    "marketplace renders no contributor list"
                ),
                remediation=(
                    "the file must be a flat JSON array of names, e.g. "
                    "[\"Simon Sigre\"]"
                ),
            )]

        if not isinstance(data, list):
            return [ValidationIssue(
                rule_name="invalid_contributors",
                severity="error",
                file_path=relative,
                message=(
                    f"must be a JSON array of names, not "
                    f"{type(data).__name__}"
                ),
                consequence=(
                    "demisto-sdk reads this file as a list of strings; the "
                    "marketplace cannot read any other shape"
                ),
                remediation='rewrite it as e.g. ["Simon Sigre"]',
            )]

        if not data:
            return [ValidationIssue(
                rule_name="invalid_contributors",
                severity="error",
                file_path=relative,
                message="is an empty array",
                consequence="a pack with no attribution is not one we ship",
                remediation="name at least one contributor, e.g. [\"Simon Sigre\"]",
            )]

        offenders = [entry for entry in data if not isinstance(entry, str) or not entry.strip()]
        if offenders:
            return [ValidationIssue(
                rule_name="invalid_contributors",
                severity="error",
                file_path=relative,
                message=(
                    f"every entry must be a non-empty name string; found "
                    f"{offenders[0]!r}"
                ),
                consequence="the marketplace cannot render the contributor list",
                remediation="replace the entry with a contributor's name",
            )]

        return []

    def _check_rule_file_sets(self, pack_path: Path) -> list[ValidationIssue]:
        """Check that every .xif has the sidecar files that register it.

        A parsing or modelling rule is a file set, not a single file, and the
        YAML descriptor is the content item: demisto-sdk enumerates the .yml
        and derives the rest from its stem, mapping .xif to .yml by suffix
        replacement. A .xif with no matching .yml is therefore invisible to
        every tool in the chain. Validation passes, upload reports success,
        the pack installs and the tenant reports the new version, but the
        rule was never deployed and no output anywhere says so.

        This is why the check is an error rather than a warning. The failure
        has no other signal: the rule simply never runs.

        Modelling rules take a third file, `<stem>_schema.json`, which
        declares the raw dataset columns the rule maps from.

        Presence is tested with is_file(), not exists(): a directory of the
        right name satisfies exists() and would pass the check.

        This covers presence only. Schema *validity* is unchecked here, and
        demisto-sdk does not cover it either in the configuration spellbook
        invokes: its default_config.toml selects fifteen path-based codes,
        none of them MR or ST, so MR100/101/106/107/108 and ST110 never run.
        A schema that is malformed JSON, an empty object, or keyed on a
        dataset the .xif does not declare passes validation today.

        Args:
            pack_path: Path to the pack directory.

        Returns:
            List of validation issues found.
        """
        issues = []

        for content_type in ("ParsingRules", "ModelingRules"):
            content_dir = pack_path / content_type
            if not content_dir.exists():
                continue

            for xif_path in sorted(content_dir.rglob("*.xif")):
                relative_path = str(xif_path.relative_to(pack_path.parent))
                descriptor = xif_path.with_suffix(".yml")

                if not descriptor.is_file():
                    issues.append(ValidationIssue(
                        rule_name="rule_missing_descriptor",
                        severity="error",
                        file_path=relative_path,
                        message=(
                            f"no matching {descriptor.name}"
                        ),
                        consequence=(
                            "without the YAML descriptor demisto-sdk never "
                            "sees this rule, so the pack uploads and installs "
                            "while the rule never deploys"
                        ),
                        remediation=(
                            f"add {descriptor.name} beside the .xif, or "
                            f"re-import the rule with `summon`, which writes "
                            f"the whole file set"
                        ),
                    ))
                    continue

                if content_type != "ModelingRules":
                    continue

                schema = xif_path.with_name(f"{xif_path.stem}_schema.json")
                if not schema.is_file():
                    issues.append(ValidationIssue(
                        rule_name="rule_missing_schema",
                        severity="error",
                        file_path=relative_path,
                        message=(
                            f"no matching {schema.name}"
                        ),
                        consequence=(
                            "the schema declares the dataset columns the rule "
                            "maps from; without it the package is incomplete "
                            "and the rule maps nothing"
                        ),
                        remediation=(
                            f"add {schema.name}, or re-import with "
                            f"`summon datamodel`, which generates it"
                        ),
                    ))

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
                            f"{content_type} only accepts {allowed} files"
                        ),
                        consequence=(
                            "the official content store rejects other suffixes"
                        ),
                        remediation=(
                            f"rename it to one of {allowed}, or move it out of "
                            f"{content_type}"
                        ),
                    ))
                elif not file_path.stem.startswith(f"{pack_name}_"):
                    issues.append(ValidationIssue(
                        rule_name="xsiam_filename_pack_prefix",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                            f"filename does not start with '{pack_name}_'"
                        ),
                        consequence=(
                            "the official content store rejects mismatched names"
                        ),
                        remediation=(
                            f"rename it to '{pack_name}_{file_path.name}'"
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

    def _is_known_model_gap(self, field: str, error: dict, data: dict) -> bool:
        """Return True for a strict-model failure the estate keeps on purpose.

        The platform fields the model does not declare, and suppression_fields
        as a list. demisto/content's CI rejects both (see
        PLATFORM_CORRELATION_FIELDS); the estate keeps them for the tenant's
        behaviour, so reporting them would only bury real findings.
        """
        if error.get("type") == "value_error.extra":
            return field in PLATFORM_CORRELATION_FIELDS
        if field in LIST_TOLERANT_FIELDS:
            return isinstance(data.get(field), list)
        return False

    def _check_strict_schemas(self, pack_path: Path) -> list[ValidationIssue]:
        """Check YAML content items against the demisto-sdk strict models.

        Catches required fields that are missing and fields the model
        forbids. demisto/content's CI applies these models as ST110; reported
        here as warnings. The platform fields a tenant export carries are
        exempt by the estate's decision (see PLATFORM_CORRELATION_FIELDS).

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
                        if self._is_known_model_gap(field, error, data):
                            continue
                        issues.append(ValidationIssue(
                            rule_name="strict_schema_mismatch",
                            severity="warning",
                            file_path=relative_path,
                            message=(
                                f"'{field}': "
                                f"{error.get('msg', 'schema mismatch')}"
                            ),
                            consequence=(
                                f"demisto/content's CI checks the item against "
                                f"{model.__name__} (ST110), so a pull request "
                                f"carrying it fails there"
                            ),
                            remediation="correct the field to match the model",
                        ))

        return issues

    def _check_unmappable_xdm_fields(self, pack_path: Path) -> list[ValidationIssue]:
        """Check modelling rule XIF files for XDM fields a rule may not assign.

        Certain XDM fields are valid in the schema but are not part of the
        event model a data model rule maps to (see xdm_fields); assigning to
        one is refused by the tenant, and a pack carrying it fails to install
        or installs without compiling. Assignments are errors. Any other occurrence inside a
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
                            f"'{finding['field']}' cannot be a mapping target "
                            f"in a data model rule"
                        ),
                        consequence=(
                            "it is not part of the data model the rule maps "
                            "to, so the tenant refuses the rule, and a pack "
                            "carrying it fails to install (a 101704 naming "
                            "nothing) or installs without compiling"
                        ),
                        remediation=(
                            "remove the assignment"
                            + (
                                "; put a group's name in "
                                "xdm.target.user.groups instead"
                                if finding["field"] == "xdm.target.user.group"
                                else ""
                            )
                        ),
                        line_number=finding["line"],
                    ))
                else:
                    issues.append(ValidationIssue(
                        rule_name="unmappable_xdm_field_reference",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                            f"'{finding['field']}' is an XDM field a data "
                            f"model rule cannot populate"
                        ),
                        consequence=(
                            "it is not part of the data model the rule maps "
                            "to, so its presence here is unusual"
                        ),
                        remediation=(
                            "confirm the occurrence is intentional, or remove it"
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
                        message="filename contains spaces",
                    consequence=(
                        "the content store rejects the file, and several "
                        "tools in the chain mis-handle the path before it "
                        "gets that far"
                    ),
                    remediation="rename it using underscores or hyphens only"
                    ))
                
                # Check for mixed separators (both underscore and hyphen)
                has_underscore = "_" in filename.replace(".yml", "").replace(".json", "").replace(".xif", "").replace(".md", "")
                has_hyphen = "-" in filename.replace(".yml", "").replace(".json", "").replace(".xif", "").replace(".md", "")
                if has_underscore and has_hyphen:
                    issues.append(ValidationIssue(
                        rule_name="filename_mixed_separators",
                        severity="warning",
                        file_path=relative_path,
                        message=(
                        "filename mixes underscores and hyphens"
                    ),
                    consequence=(
                        "nothing rejects it, but the inconsistency makes the "
                        "pack harder to match by pattern and diverges from "
                        "the rest of the store"
                    ),
                    remediation="pick one separator and use it throughout the name"
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
                        line_number=line_num,
                        consequence=rule.consequence,
                        remediation=rule.remediation,
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
                lines.extend(render_issue(issue, "ERROR"))

        if warnings:
            if errors:
                lines.append("")
            lines.append("XSIAM Validation Warnings:")
            for issue in warnings:
                lines.extend(render_issue(issue, "WARN"))

        return "\n".join(lines)


def render_issue(issue: ValidationIssue, label: str) -> list[str]:
    """Render one finding as tagged lines.

    Module-level so a finding raised outside this validator - demisto-sdk
    failing to finish, reported by pack_builder - reads exactly like one raised
    inside it. Two renderers for one contract is how the contract drifts.

    Args:
        issue: The finding.
        label: The tag, ERROR or WARN.

    Returns:
        The lines, each carrying the tag.
    """
    # EVERY line carries the [ERROR]/[WARN] tag, including the continuation
    # lines. The long-standing contract is that findings are greppable by that
    # tag; an indented continuation would return the statement and silently
    # drop the reason and the fix, which is worse than not emitting them - the
    # reader would not know they had been truncated.
    location = issue.file_path
    if issue.line_number:
        location += f":{issue.line_number}"
    out = [f"[{label}] {location}: {issue.message}"]
    if issue.consequence:
        out.append(f"[{label}]   why: {issue.consequence}")
    if issue.remediation:
        out.append(f"[{label}]   fix: {issue.remediation}")
    # Always present: the stable identifier to key on, so a caller can match a
    # rule without matching prose that is free to change.
    out.append(f"[{label}]   rule: {issue.rule_name}")
    return out


# demisto-sdk skips a child of a content folder by this name (the old test
# file layout) before treating the rest as content items.
SDK_SKIPPED_CHILD = "test_data"

# An item whose toversion is below this is never parsed, so no validator sees
# it (constants.MARKETPLACE_MIN_VERSION in the pinned SDK).
SDK_MIN_TOVERSION = (6, 0, 0)

# DockerValidator.should_run skips any item whose path contains this, case
# folded. API modules are imported into other code rather than run.
SDK_DOCKER_EXEMPT_PATH = "apimodule"

# The code the native docker-image rule stands in for, so an existing
# `.pack-ignore` suppression written for demisto-sdk keeps working.
DOCKER_IMAGE_SDK_CODE = "DO104"


class _Yaml12BoolLoader(yaml.SafeLoader):
    """PyYAML with YAML 1.2 booleans: only true/false in their three casings.

    PyYAML follows YAML 1.1, where yes/no/on/off are booleans too. demisto-sdk's
    loader follows 1.2 and keeps them as strings, and it is the SDK's reading
    that decides what an item IS - so `isllm: yes` must not exempt a script
    here that the SDK reads as a string.
    """


_Yaml12BoolLoader.yaml_implicit_resolvers = {
    first: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Yaml12BoolLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)


def _root_key_line(text: str, key: str) -> int | None:
    """Return the line a top-level YAML key is on, or None when it is absent.

    The key may be quoted, and a Windows-authored file may open with a BOM.
    An indented occurrence belongs to a nested mapping and is not the root.
    """
    pattern = re.compile(rf"""^﻿?["']?{re.escape(key)}["']?\s*:""")
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.match(line):
            return number
    return None


def content_descriptors(content_dir: Path) -> list[Path]:
    """Return the descriptor YAMLs demisto-sdk treats as content items.

    Mirrors PackParser.parse_pack_folders and ContentItemParser in the pinned
    SDK, because a check standing in for an SDK validator must look at the
    items that validator looked at, and no others:

    - every .yml directly in the folder is a unified item, whatever its name;
    - in a package directory, the only .yml is the descriptor whatever its
      stem, and when there are several, <Package>.yml wins;
    - a child named test_data is skipped, and nothing deeper is considered.

    Where a package holds several .yml and none is <Package>.yml the SDK takes
    the first its directory listing returns, which is filesystem order; this
    takes the first by name so the answer does not change between machines.

    Args:
        content_dir: The Integrations or Scripts directory of a pack.

    Returns:
        The descriptor paths, sorted.
    """
    if not content_dir.is_dir():
        return []

    descriptors = []
    for child in sorted(content_dir.iterdir()):
        if child.name == SDK_SKIPPED_CHILD:
            continue
        if child.is_file():
            if child.suffix == ".yml":
                descriptors.append(child)
            continue
        if not child.is_dir():
            continue
        ymls = sorted(p for p in child.iterdir() if p.suffix == ".yml" and p.is_file())
        if not ymls:
            continue
        preferred = child / f"{child.name}.yml"
        descriptors.append(preferred if preferred in ymls else ymls[0])
    return descriptors


# How the SDK's pydantic models coerce a boolean field. `deprecated` is read
# raw and coerced by the model, so `deprecated: yes` IS deprecated to the SDK
# even though its YAML 1.2 loader keeps "yes" a string.
SDK_TRUTHY_STRINGS = {"true", "yes", "on", "1", "t", "y"}


def _sdk_bool(value) -> bool:
    """Return how demisto-sdk's models read a boolean field."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    return isinstance(value, str) and value.strip().lower() in SDK_TRUTHY_STRINGS


def _version_tuple(value) -> tuple[int, ...] | None:
    """Parse a dotted version, or None when it is not one."""
    parts = str(value).strip().split(".")
    if not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _suppressed_codes(pack_path: Path) -> tuple[set[str], dict[str, list[str]]]:
    """Read the codes a pack's .pack-ignore suppresses, the way the SDK does.

    Returns the [pack] section's codes, which apply to every item, and each
    [file:<name>] section's codes keyed by <name>. The SDK reads a file
    section's FIRST value and splits it on commas without stripping, so
    `ignore=BA101, DO104` suppresses " DO104" rather than DO104 there; that is
    mirrored rather than corrected, or a suppression would work here that fails
    upstream. The [pack] section is stripped, as the SDK strips it.
    """
    pack_ignore = pack_path / ".pack-ignore"
    if not pack_ignore.is_file():
        return set(), {}
    parser = configparser.ConfigParser(allow_no_value=True)
    try:
        parser.read(pack_ignore, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError):
        return set(), {}

    pack_codes: set[str] = set()
    if parser.has_section("pack"):
        value = parser.get("pack", "ignore", fallback=None)
        if value:
            pack_codes = {code.strip() for code in value.split(",") if code.strip()}

    file_codes: dict[str, list[str]] = {}
    for section in parser.sections():
        if not section.startswith("file:"):
            continue
        items = list(parser.items(section))
        if items and items[0][1]:
            file_codes[section[len("file:"):]] = items[0][1].split(",")
    return pack_codes, file_codes


# Code files that make a script package code-backed. A test module is not the
# script's code.
SCRIPT_CODE_SUFFIXES = {".py", ".ps1", ".js"}


def _carried_code(yml_path: Path, content_dir: Path, data: dict) -> str:
    """Name the code a script carries, or return "" when it carries none.

    Inline code in `script:` (a unified file), or a code file beside the
    descriptor in its package.
    """
    body = data.get("script")
    if isinstance(body, str) and body.strip() not in ("", "-"):
        return "inline code in `script:`"
    if yml_path.parent != content_dir:
        for sibling in sorted(yml_path.parent.iterdir()):
            if (sibling.suffix in SCRIPT_CODE_SUFFIXES
                    and not sibling.stem.endswith("_test")):
                return sibling.name
    return ""


def check_docker_images(pack_path: Path) -> list[ValidationIssue]:
    """Check Python and PowerShell content names the container it runs in.

    This is demisto-sdk's DO104, performed natively rather than selected,
    because DO104 cannot run on a pack holding a prompt-backed script. Such a
    script (`isllm: true`) has no code and so no container, which DO104 does
    not know: it reports the script as missing an image. Worse, to word that
    report it asks Docker Hub for the newest image to name in the message. A
    prompt script's `type: python` carries no `subtype`, the SDK assumes
    python2, and there is no demisto/python2 on Docker Hub (demisto's Python 2
    image is demisto/python), so the lookup gets a 401, raises, and the whole
    SDK run dies with no finding at all.

    It keeps DO104's reach as well as its rule, so the gate is not quietly
    wider or narrower than the one it replaces: the same items (see
    content_descriptors), and the same exclusions - deprecated items, items
    whose toversion is below 6.0.0, API modules, and a DO104 suppression in
    .pack-ignore. The one addition is the prompt-script exemption.

    Module-level so pack_builder runs it inside the demisto-sdk stage, where
    DO104 ran. It therefore blocks build, validate and validate-all as DO104
    did, and nothing that DO104 never blocked.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        List of validation issues found.
    """
    content_root = pack_path.parent.parent
    pack_codes, file_codes = _suppressed_codes(pack_path)
    if DOCKER_IMAGE_SDK_CODE in pack_codes:
        return []

    issues = []
    for directory, kind in (("Integrations", "integration"), ("Scripts", "script")):
        for yml_path in content_descriptors(pack_path / directory):
            if SDK_DOCKER_EXEMPT_PATH in str(yml_path).lower():
                continue
            relative = str(yml_path.relative_to(content_root))
            if (DOCKER_IMAGE_SDK_CODE in file_codes.get(yml_path.name, [])
                    or DOCKER_IMAGE_SDK_CODE in file_codes.get(relative, [])):
                continue
            try:
                data = yaml.load(yml_path.read_text(encoding="utf-8"), Loader=_Yaml12BoolLoader)
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                # A descriptor that does not parse is reported by demisto-sdk;
                # do not duplicate it with a worse message.
                continue
            if not isinstance(data, dict):
                continue
            if _sdk_bool(data.get("deprecated")):
                continue
            toversion = _version_tuple(data.get("toversion", ""))
            if toversion is not None and toversion < SDK_MIN_TOVERSION:
                continue

            # An integration keeps its runtime under `script:`, a script at its
            # root. DO104 treats a missing mapping as an empty one.
            runtime = data.get("script") if kind == "integration" else data
            if not isinstance(runtime, dict):
                runtime = {}

            script_type = runtime.get("type")
            if script_type in CONTAINERLESS_SCRIPT_TYPES:
                continue
            if runtime.get("dockerimage"):
                continue
            # The YAML 1.2 boolean only. A quoted "true", or a yes/on that
            # demisto-sdk reads as a string, is reported rather than guessed
            # at: what the platform makes of a string here is unverified.
            if kind == "script" and data.get("isllm") is True:
                continue

            file_name = yml_path.name
            prompt_keys = sorted(PROMPT_SCRIPT_KEYS & data.keys()) if kind == "script" else []
            code = _carried_code(yml_path, pack_path / directory, data) if prompt_keys else ""
            if prompt_keys and code:
                # Setting isllm here would pass the check and silently drop
                # the code; removing the prompt keys is just as valid a fix,
                # and only the author knows which was meant.
                message = (
                    f"script carries both code ({code}) and "
                    f"{' and '.join(prompt_keys)}, and names no dockerimage"
                )
                consequence = (
                    "it is neither a valid code script nor a valid prompt "
                    "script; marked prompt-backed its code would be ignored, "
                    "and as code it needs a container it does not name "
                    "(DO104)"
                )
                image = DOCKER_IMAGE_BY_TYPE.get(script_type, "demisto/python3")
                remediation = (
                    f"decide which it is. Code: remove "
                    f"{', '.join(prompt_keys)} (and model/promptConfig) from "
                    f"{file_name} and add `dockerimage: {image}:<tag>` at its "
                    f"root. Prompt: delete the code and set `isllm: true`"
                )
            elif prompt_keys:
                message = (
                    f"script carries {' and '.join(prompt_keys)} but is not "
                    f"marked prompt-backed, and names no dockerimage"
                )
                consequence = (
                    "without `isllm: true` it is treated as code, which needs a "
                    "container it does not name; demisto-sdk's default gate "
                    "rejects that as DO104"
                )
                remediation = (
                    f"set `isllm: true` (the YAML boolean: not quoted, not "
                    f"yes/on) at the root of {file_name}; a prompt script runs "
                    f"no code and takes no dockerimage"
                )
            else:
                where = "under the `script:` key" if kind == "integration" else "at the root"
                image = DOCKER_IMAGE_BY_TYPE.get(script_type)
                message = f"{kind} names no dockerimage"
                consequence = (
                    "Python and PowerShell content runs in a container and this "
                    "one names none; demisto-sdk's default gate rejects it as "
                    "DO104"
                )
                if image:
                    remediation = (
                        f"add `dockerimage: {image}:<tag>` {where} of "
                        f"{file_name}, taking a current tag from "
                        f"https://hub.docker.com/r/{image}/tags"
                    )
                else:
                    remediation = (
                        f"set `type` to python, powershell or javascript {where} "
                        f"of {file_name}, and for python or powershell add a "
                        f"matching `dockerimage`"
                    )

            issues.append(ValidationIssue(
                rule_name="missing_docker_image",
                severity="error",
                file_path=str(yml_path.relative_to(pack_path.parent)),
                message=message,
                consequence=consequence,
                remediation=remediation,
            ))
    return issues


def _value_at(data, path: tuple) -> object:
    """Follow a path of keys and list indexes, or return None where it breaks."""
    for step in path:
        if isinstance(step, int):
            if not isinstance(data, list) or len(data) <= step:
                return None
            data = data[step]
        else:
            if not isinstance(data, dict):
                return None
            data = data.get(step)
    return data


def _rn_display_names(pack_path: Path, header: str) -> set[str]:
    """Return the display names RN114 compares a header's item headers to.

    YAML is read with YAML 1.2 booleans, as the SDK reads it, so an item
    named Yes or On keeps its name rather than becoming a bool.
    """
    folder, layout, name_path, fallback = RN_DISPLAY_NAME_SOURCES[header]
    content_dir = pack_path / folder
    if not content_dir.is_dir():
        return set()
    if layout == "package":
        files = content_descriptors(content_dir)
    elif layout == "flat-yml":
        files = sorted(content_dir.glob("*.yml"))
    elif layout == "nested-yml":
        files = sorted(content_dir.rglob("*.yml"))
    else:
        files = sorted(content_dir.glob("*.json"))

    names = set()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            if layout == "json":
                data = json.loads(text)
            else:
                data = yaml.load(text, Loader=_Yaml12BoolLoader)
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError):
            continue
        value = _value_at(data, name_path)
        if not value and fallback:
            value = _value_at(data, fallback)
        if isinstance(value, str) and value:
            names.add(value)
    return names


def _latest_release_note(pack_path: Path) -> Path | None:
    """Return the note demisto-sdk's release-note validators read.

    That is the highest-versioned ReleaseNotes/*.md (get_pack_latest_rn_version),
    not the one currentVersion names: the two differ when a version is
    rolled back or re-scaffolded, and the SDK reads the higher. A stem that
    is not a version is skipped.
    """
    notes_dir = pack_path / "ReleaseNotes"
    if not notes_dir.is_dir():
        return None
    candidates = []
    for path in notes_dir.glob("*.md"):
        version = _version_tuple(path.stem.replace("_", "."))
        if version is not None and path.is_file():
            candidates.append((version, path.name, path))
    return max(candidates)[2] if candidates else None


def _pack_is_deprecated(metadata: dict) -> bool:
    """Return whether demisto-sdk treats the pack as deprecated."""
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not isinstance(description, str):
        return False
    return bool(PACK_NAME_DEPRECATED.match(name)) and any(
        pattern.match(description) for pattern in PACK_DESC_DEPRECATED
    )


def _pack_has_items(pack_path: Path) -> bool:
    """Return whether the pack holds a content item of any kind."""
    for child in pack_path.iterdir():
        if (not child.is_dir() or child.name.startswith(".")
                or child.name in RN_NON_CONTENT_DIRS):
            continue
        if any(p.suffix in (".yml", ".json") and p.is_file() for p in child.rglob("*")):
            return True
    return False


def check_release_notes(pack_path: Path) -> list[ValidationIssue]:
    """Check the latest release note's headers the way demisto-sdk does.

    Mirrors RN113 (a first-level `####` header must be a content type), RN114
    (it must also map back to a content type, and each `#####` item header
    must equal the display name of an item of that type in this pack) and
    RN115 (a content-type header must have item headers under it). The note
    read is the one the SDK reads: the highest-versioned in ReleaseNotes/.

    Warnings, not errors. The SDK runs these only on a pack git reports as
    MODIFIED - a pack already merged upstream and being updated - so they do
    not fail a first submission, and spellbook's own `validate -i` never runs
    them at all. Each code honours a `.pack-ignore` suppression on its own,
    as the SDK does: ignoring RN113 does not silence RN114 or RN115 about the
    same header. A deprecated pack is skipped, as the SDK skips it.

    Args:
        pack_path: Path to the pack directory.

    Returns:
        List of validation issues found.
    """
    try:
        metadata = json.loads((pack_path / "pack_metadata.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        # Unreadable metadata is pack_metadata_unreadable's to report.
        return []
    if not isinstance(metadata, dict) or _pack_is_deprecated(metadata):
        return []
    note = _latest_release_note(pack_path)
    if note is None:
        return []
    # Decoded without newline translation: the SDK keeps a CRLF note's \r,
    # so its `$\n` header pattern finds no section in one, and neither may
    # this. A note that is not UTF-8 the SDK still decodes; latin-1 never
    # fails, and the headers that matter are ASCII.
    try:
        raw = note.read_bytes()
    except OSError:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    pack_codes, file_codes = _suppressed_codes(pack_path)
    suppressed = pack_codes | set(file_codes.get(note.name, []))
    relative = str(note.relative_to(pack_path.parent))
    pack_wide = "`## <pack display name>`"
    check_items = not _sdk_bool(metadata.get("hidden")) and _pack_has_items(pack_path)

    def line_of(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    issues = []
    # Each section's header, line, whether any item-pattern matched, and its
    # named items with their lines.
    sections = []
    for match in RN_TYPE_SECTION.finditer(text):
        body_group = 2 if match.group(1) else 4
        header = match.group(1) or match.group(3)
        body = match.group(body_group) or ""
        if body == "":
            # demisto-sdk drops an empty section body and then indexes past
            # it: RN114 and RN115 raise, and the run aborts. No suppression
            # covers a crash.
            issues.append(ValidationIssue(
                rule_name="release_note_header_without_items",
                severity="warning",
                file_path=relative,
                line_number=line_of(match.start()),
                message=f"'#### {header}' is followed directly by another '####' header",
                consequence=(
                    "an empty section crashes demisto-sdk's release-note "
                    "validators, so validation aborts in demisto/content's CI "
                    "on any pull request that updates the pack once it is merged"
                ),
                remediation=(
                    "give the section its `##### <item display name>` entries, "
                    "or remove the header"
                ),
            ))
            continue
        body_start = match.start(body_group)
        found = list(RN_ITEM_SECTION.finditer(body))
        items = []
        for item_match in found:
            values = [value for value in item_match.groups() if value]
            if values:
                items.append((values[0], line_of(body_start + item_match.start())))
        sections.append((header, line_of(match.start()), bool(found), items))

    # RN115's view: sections merge by content type, and a section with no
    # item-pattern match at all resets that type to empty - so a later empty
    # duplicate fails it and an earlier one does not.
    rn115: dict[str, list] = {}
    rn115_line: dict[str, int] = {}
    # RN114's view: every named item, by content type, without resets.
    rn114: dict[str, list] = {}
    for header, line, matched, items in sections:
        if not matched:
            rn115[header] = []
            rn115_line[header] = line
        elif items:
            rn115.setdefault(header, []).extend(items)
            rn115_line.setdefault(header, line)
        for name, item_line in items:
            name = name.removeprefix(RN_NEW_ITEM_PREFIX) if RN_NEW_ITEM_PREFIX in name else name.rstrip()
            if header == "Playbooks" and name in RN_PLAYBOOK_SUBHEADERS:
                continue
            rn114.setdefault(header, []).append((name, item_line))

    rn114_runs = check_items and "RN114" not in suppressed
    rejected = set()
    for header, line, _matched, _items in sections:
        if header in rejected:
            continue
        codes = []
        if header not in RN_CONTENT_TYPE_HEADERS and "RN113" not in suppressed:
            codes.append("RN113")
        if (rn114_runs and rn114.get(header)
                and (header not in RN_CONTENT_TYPE_HEADERS or header in RN114_REJECTED_HEADERS)):
            codes.append("RN114")
        if not codes:
            continue
        rejected.add(header)
        if header == "Modeling Rules Schema":
            remediation = "list a schema change under `#### Modeling Rules`, naming the rule"
        elif header == "Case Layouts":
            remediation = "list the layout under `#### Layouts`"
        else:
            remediation = (
                f"put a pack-wide note under {pack_wide}, or name the content "
                f"type, e.g. `#### Integrations` or `#### Correlation Rules`, "
                f"with `##### <item display name>` under it"
            )
        issues.append(ValidationIssue(
            rule_name="release_note_header_not_content_type",
            severity="warning",
            file_path=relative,
            line_number=line,
            message=(
                f"first-level header '#### {header}' is not a content type"
                + (" RN114 accepts" if header in RN114_REJECTED_HEADERS else "")
            ),
            consequence=(
                f"demisto/content's CI rejects it ({' and '.join(codes)}) on "
                f"any pull request that updates the pack once it is merged"
            ),
            remediation=remediation,
        ))

    if "RN115" not in suppressed:
        for header, items in rn115.items():
            # One finding per defect: a header already rejected is fixed by
            # the same edit.
            if items or header in rejected:
                continue
            issues.append(ValidationIssue(
                rule_name="release_note_header_without_items",
                severity="warning",
                file_path=relative,
                line_number=rn115_line[header],
                message=f"'#### {header}' has no '##### <item>' header under it",
                consequence=(
                    "demisto/content's CI rejects the note (RN115) on any pull "
                    "request that updates the pack once it is merged"
                ),
                remediation=(
                    "name each changed item under it as `##### <item display "
                    f"name>`, or move a pack-wide note under {pack_wide}"
                ),
            ))

    if rn114_runs:
        for header, entries in rn114.items():
            if (header not in RN_CONTENT_TYPE_HEADERS or header in RN114_REJECTED_HEADERS
                    or header not in RN_DISPLAY_NAME_SOURCES):
                continue
            names = _rn_display_names(pack_path, header)
            seen = set()
            for name, item_line in entries:
                if name in names or name in seen:
                    continue
                seen.add(name)
                if names:
                    listed = sorted(names)
                    choices = ", ".join(listed[:8]) + (", ..." if len(listed) > 8 else "")
                    remediation = (
                        f"use the item's display name exactly - here: {choices}; "
                        f"mark a new item as `##### New: <name>`"
                    )
                else:
                    remediation = (
                        f"this pack has no {header}; remove the section, or "
                        f"move the note under {pack_wide}"
                    )
                issues.append(ValidationIssue(
                    rule_name="release_note_item_not_in_pack",
                    severity="warning",
                    file_path=relative,
                    line_number=item_line,
                    message=(
                        f"'##### {name}' under '#### {header}' matches no item "
                        f"of that type in this pack"
                    ),
                    consequence=(
                        "demisto/content's CI rejects the note (RN114) on any "
                        "pull request that updates the pack once it is merged; "
                        "an item header must equal the item's display name"
                    ),
                    remediation=remediation,
                ))
    return issues
