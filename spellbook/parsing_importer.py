# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Parsing Rule Importer

Turns raw XIF text into a complete parsing rule package, the way
modeling_importer does for data model rules.

A parsing rule is a file set, not a file: the YAML descriptor is the content
item demisto-sdk enumerates, and the XIF is found by stem. Creating the pair
by hand is easy to get half right, and a lone XIF is invisible to every tool
in the chain, so the pack uploads and installs while the rule never deploys.
Emitting both together removes that failure.

Unlike the modelling importer, there is nothing in demisto-sdk to mirror
here: the SDK never reads the `[INGEST: ...]` header, treating the XIF as
opaque and binding it purely by filename stem. The header is parsed only to
name the package after its target dataset.
"""

import re

import yaml

from spellbook.rule_importer import RuleImporterBase


# The INGEST header names the dataset the rule writes into. Quotes are
# optional in XIF, and both forms appear in tenant exports.
TARGET_DATASET_PATTERN = re.compile(
    r'target_dataset\s*=\s*"?([a-zA-Z_0-9]+)"?', re.IGNORECASE
)

INGEST_HEADER_PATTERN = re.compile(r"\[\s*INGEST\s*:", re.IGNORECASE)

# Validator PR101 requires the id to end with 'ParsingRule' and the name to
# end with 'Parsing Rule'.
PARSING_RULE_ID_SUFFIX = "ParsingRule"
PARSING_RULE_NAME_SUFFIX = "Parsing Rule"

DEFAULT_FROM_VERSION = "8.3.0"


class ParsingRuleImporter(RuleImporterBase):
    """Creates parsing rule packages from XIF text."""

    def import_from_xif(
        self,
        xif_content: str,
        pack_name: str,
        name: str | None = None,
    ) -> dict:
        """Import a parsing rule from XIF text.

        Args:
            xif_content: Raw XIF rule text.
            pack_name: Target pack name.
            name: Base name for the rule, or None to derive one from the
                target dataset. The 'ParsingRule' suffix is appended
                automatically.

        Returns:
            Result dictionary describing the package that was written.

        Raises:
            ValueError: If the input is not a usable parsing rule, or the
                target pack is missing or unsafe to write to.
        """
        xif = self._normalise_line_endings(xif_content)

        if not xif.strip():
            raise ValueError("No XIF content provided")

        if not INGEST_HEADER_PATTERN.search(xif):
            raise ValueError(
                "Input does not look like a parsing rule: no [INGEST: ...] header "
                "found. Copy the rule text from the tenant rule editor, including "
                "its header line."
            )

        datasets = self.extract_target_datasets(xif)
        if not datasets:
            raise ValueError(
                "No target_dataset found in the [INGEST:] header. Expected a header "
                'of the form [INGEST:vendor="acme", product="widget", '
                'target_dataset="acme_widget_raw", no_hit=drop].'
            )

        pack_path = self.packs_dir / pack_name
        if not pack_path.exists():
            raise ValueError(f"Pack not found: {pack_name}")

        rules_dir = pack_path / "ParsingRules"
        if rules_dir.is_symlink():
            raise ValueError(
                "ParsingRules directory is a symlink; refusing to write "
                "through it to prevent path escape"
            )

        resolved_stem, display_name = self._derive_names(pack_name, datasets, name)
        self._validate_stem(resolved_stem, PARSING_RULE_ID_SUFFIX, "PR101")

        package_dir = rules_dir / resolved_stem
        self._assert_within(package_dir, pack_path)
        if package_dir.is_symlink():
            raise ValueError(
                f"Package directory '{resolved_stem}' is a symlink; refusing to "
                "write through it to prevent path escape"
            )

        package_dir.mkdir(parents=True, exist_ok=True)

        files = [
            self._write(
                package_dir,
                f"{resolved_stem}.yml",
                self._build_yaml(resolved_stem, display_name),
                pack_path,
            ),
            self._write(
                package_dir, f"{resolved_stem}.xif", self._build_xif(xif), pack_path
            ),
        ]

        warnings = []
        if len(datasets) > 1:
            warnings.append(
                f"XIF declares {len(datasets)} target datasets "
                f"({', '.join(datasets)}); the package is named after the first"
            )
        if "_time" not in xif:
            warnings.append(
                "rule never assigns _time - events will carry their ingestion "
                "time, so confirm the source has no event timestamp to parse"
            )

        return {
            "stem": resolved_stem,
            "package_dir": str(package_dir),
            "datasets": datasets,
            "files": files,
            "warnings": warnings,
        }

    def extract_target_datasets(self, xif: str) -> list[str]:
        """Return the target datasets declared in the XIF, ordered and deduped."""
        seen = []
        for match in TARGET_DATASET_PATTERN.finditer(xif):
            dataset = match.group(1).strip('"')
            if dataset and dataset not in seen:
                seen.append(dataset)
        return seen

    def _derive_names(
        self, pack_name: str, datasets: list[str], name: str | None
    ) -> tuple[str, str]:
        """Derive the package stem and the display name for the rule.

        Named after the target dataset by default, so a pack can carry a
        parsing rule per source without collision, matching how the modelling
        importer names its packages. The pack name is only a fallback.
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
        stem = "".join(capitalised) + PARSING_RULE_ID_SUFFIX
        display_name = " ".join(capitalised) + f" {PARSING_RULE_NAME_SUFFIX}"
        return stem, display_name

    def _strip_rule_suffix(self, name: str) -> str:
        """Drop a trailing ParsingRule / Parsing Rule suffix if the user
        included one, so it is not doubled when the suffix is re-appended."""
        collapsed = re.sub(r"[^a-z0-9]", "", name.lower())
        if collapsed.endswith("parsingrule") or collapsed.endswith("parsingrules"):
            return re.sub(
                r"[\s_-]*parsing[\s_-]*rules?\s*$", "", name, flags=re.IGNORECASE
            )
        return name

    def _build_yaml(self, stem: str, display_name: str) -> str:
        """Build the rule YAML.

        The rules and samples keys must be empty strings; the XIF is located
        by filename stem, not by these values. tags is a list for parsing
        rules, unlike modelling rules where it is a string.
        """
        data = {
            "id": stem,
            "name": display_name,
            "fromversion": DEFAULT_FROM_VERSION,
            "tags": [],
            "rules": "",
            "samples": "",
        }
        return yaml.dump(
            data, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    def _build_xif(self, xif: str) -> str:
        """Return the rule text with a single trailing newline."""
        return xif.rstrip("\n") + "\n"
