# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Pack Template Module

Creates new content pack scaffolding from templates.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import yaml


class PackTemplate:
    """Creates new pack structures from templates."""

    CONTENT_DIRECTORIES = [
        "Integrations",
        "Scripts",
        "Playbooks",
        "IncidentTypes",
        "IncidentFields",
        "Layouts",
        "Classifiers",
        "CorrelationRules",
        "ParsingRules",
        "ModelingRules",
        "XSIAMDashboards",
        "XSIAMReports",
        "Triggers",
        "Jobs",
        "XDRCTemplates",
        "ReleaseNotes",
    ]

    XSIAM_DIRECTORIES = [
        "CorrelationRules",
        "ParsingRules",
        "ModelingRules",
        "XSIAMDashboards",
        "XSIAMReports",
        "Triggers",
        "Jobs",
        "XDRCTemplates",
    ]

    def __init__(self, config_path: str = "spellbook.yaml"):
        """
        Initialise the pack template generator.

        Args:
            config_path: Path to the spellbook configuration file.
        """
        self.config = self._load_config(config_path)
        self.packs_dir = Path(self.config.get("packs_directory", "Packs"))
        self.defaults = self.config.get("defaults", {})

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        path = Path(config_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def create_pack(
        self,
        pack_name: str,
        description: str = "",
        author: Optional[str] = None,
        categories: Optional[List[str]] = None,
        create_directories: Optional[List[str]] = None
    ) -> Path:
        """
        Create a new pack with standard structure.

        Args:
            pack_name: Name of the pack (no spaces).
            description: Short description of the pack.
            author: Author name (uses default if not provided).
            categories: List of categories.
            create_directories: Specific directories to create.

        Returns:
            Path to the created pack directory.
        """
        pack_path = self.packs_dir / pack_name
        pack_path.mkdir(parents=True, exist_ok=True)

        self._create_metadata(
            pack_path,
            pack_name,
            description,
            author,
            categories
        )

        self._create_readme(pack_path, pack_name, description)

        self._create_pack_ignore(pack_path)

        self._create_secrets_ignore(pack_path)

        directories = create_directories or self.CONTENT_DIRECTORIES
        for directory in directories:
            dir_path = pack_path / directory
            dir_path.mkdir(exist_ok=True)
            gitkeep = dir_path / ".gitkeep"
            gitkeep.touch()

        print(f"Created pack: {pack_path}")
        return pack_path

    def _create_metadata(
        self,
        pack_path: Path,
        pack_name: str,
        description: str,
        author: Optional[str],
        categories: Optional[List[str]]
    ) -> None:
        """Create pack_metadata.json file."""
        metadata = {
            "name": pack_name,
            "description": description or f"{pack_name} content pack",
            "support": self.defaults.get("support", "community"),
            "currentVersion": "1.0.0",
            "author": author or self.defaults.get("author", ""),
            "url": self.defaults.get("url", ""),
            "email": self.defaults.get("email", ""),
            "categories": categories or self.defaults.get("categories", []),
            "tags": self.defaults.get("tags", []),
            "useCases": self.defaults.get("useCases", []),
            "keywords": self.defaults.get("keywords", []),
            "marketplaces": self.defaults.get(
                "marketplaces",
                ["xsoar", "marketplacev2"]
            ),
            "githubUser": []
        }

        metadata_path = pack_path / "pack_metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            f.write("\n")

    def _create_readme(
        self,
        pack_path: Path,
        pack_name: str,
        description: str
    ) -> None:
        """Create README.md file."""
        readme_content = f"""# {pack_name}

{description or 'Content pack for Cortex Platform.'}

## Overview

This pack contains content for use with Cortex Platform.

## Content Items

### Parsing Rules

Rules for parsing raw log data into structured fields.

### Modelling Rules

Rules for mapping parsed data to the XDM (Cross Data Model) schema.

### Correlation Rules

Detection rules that identify security events and generate alerts.

### XSIAM Dashboards

Visual dashboards for monitoring and analysis.

### XSIAM Reports

Report templates for scheduled reporting.

### Integrations

(List integrations here)

### Scripts

(List scripts here)

### Playbooks

(List playbooks here)

### Triggers

Automation triggers for event-driven workflows.

### Jobs

Scheduled jobs for recurring tasks.

## Installation

Upload the pack zip file to your Cortex Platform instance.

## Requirements

- Cortex Platform version 6.0 or later

## Support

For support, please refer to the pack metadata for contact information.
"""
        readme_path = pack_path / "README.md"
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme_content)

    def _create_pack_ignore(self, pack_path: Path) -> None:
        """Create .pack-ignore file."""
        content = """# Pack ignore file
# Use this file to ignore specific linter errors or tests

# Ignore a specific test
# [file:playbook-Test.yml]
# ignore=auto-test

# Ignore linter errors
# [file:integration.yml]
# ignore=IN126,PA116

# Require network for tests
# [tests_require_network]
# integration-id
"""
        ignore_path = pack_path / ".pack-ignore"
        with open(ignore_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _create_secrets_ignore(self, pack_path: Path) -> None:
        """Create .secrets-ignore file."""
        content = """# Secrets ignore file
# Add words that should be allowed in secret scanning

# Example allowed words:
# example_api_key
# test_token
"""
        secrets_path = pack_path / ".secrets-ignore"
        with open(secrets_path, "w", encoding="utf-8") as f:
            f.write(content)

    def _create_correlation_rule(self, pack_path: Path, pack_name: str) -> None:
        """Create sample correlation rule for Cortex Platform.
        
        Follows the demisto-sdk correlationrule.yml schema with all required
        fields. Based on working examples from demisto/content repository.
        """
        rules_dir = pack_path / "CorrelationRules"
        rules_dir.mkdir(exist_ok=True)

        rule_name = f"{pack_name} - Multiple Failed Login Attempts"
        vendor = pack_name.lower()
        dataset = f"{vendor}_raw"
        global_id = str(uuid.uuid4())

        rule_yml = f"""action: ALERTS
alert_category: CREDENTIAL_ACCESS
alert_description: Multiple failed login attempts detected from $xdm.source.ipv4 targeting $xdm.target.user.username which may indicate a brute force attack.
alert_domain: DOMAIN_SECURITY
alert_fields:
  actor_effective_username: xdm.source.user.username
  agent_hostname: xdm.source.host.hostname
alert_name: {pack_name} - Brute Force Attack Detected
alert_type: null
dataset: alerts
description: Detects multiple failed authentication attempts from a single source within a short time window indicating a potential brute force attack.
drilldown_query_timeframe: ALERT
execution_mode: REAL_TIME
fromversion: 8.4.0
global_rule_id: {global_id}
investigation_query_link: dataset = {dataset} | filter user = $xdm.target.user.username
is_enabled: true
mapping_strategy: CUSTOM
mitre_defs:
  TA0006 - Credential Access:
  - T1110 - Brute Force
name: {rule_name}
severity: SEV_030_MEDIUM
suppression_duration: 1 hours
suppression_enabled: true
suppression_fields:
  - xdm.source.ipv4
  - xdm.target.user.username
xql_query: |
  datamodel dataset = {dataset}
  | filter xdm.event.type = "AUTHENTICATION" and xdm.event.outcome = "FAILED"
  | fields xdm.event.type, xdm.event.outcome, xdm.source.ipv4, xdm.source.host.hostname, xdm.target.user.username, xdm.source.user.username
"""

        rule_filename = rule_name.replace(" ", "_").replace("-", "_")
        rule_path = rules_dir / f"{rule_filename}.yml"
        with open(rule_path, "w", encoding="utf-8") as f:
            f.write(rule_yml)

        self._create_scheduled_correlation_rule(rules_dir, pack_name, dataset)

    def _create_scheduled_correlation_rule(self, rules_dir: Path, pack_name: str, dataset: str) -> None:
        """Create sample scheduled correlation rule for Cortex Platform.
        
        Demonstrates how to configure a CRON-based scheduled correlation rule
        instead of real-time execution. Requires crontab, execution_mode, and
        search_window fields.
        """
        rule_name = f"{pack_name} - Multiple Failed Login Attempts-Scheduled"
        global_id = str(uuid.uuid4())

        rule_yml = f"""action: ALERTS
alert_category: CREDENTIAL_ACCESS
alert_description: Multiple failed login attempts detected from $xdm.source.ipv4 targeting $xdm.target.user.username which may indicate a brute force attack.
alert_domain: DOMAIN_SECURITY
alert_fields:
  actor_effective_username: xdm.source.user.username
  agent_hostname: xdm.source.host.hostname
alert_name: {pack_name} - Brute Force Attack Detected-Scheduled
alert_type: null
crontab: '*/10 * * * *'
dataset: alerts
description: Detects multiple failed authentication attempts from a single source using scheduled execution. Runs every 10 minutes with a 15 minute search window.
drilldown_query_timeframe: ALERT
execution_mode: SCHEDULED
fromversion: 8.4.0
global_rule_id: {global_id}
investigation_query_link: dataset = {dataset} | filter user = $xdm.target.user.username
is_enabled: true
mapping_strategy: CUSTOM
mitre_defs:
  TA0006 - Credential Access:
  - T1110 - Brute Force
name: {rule_name}
search_window: 15 minutes
severity: SEV_030_MEDIUM
suppression_duration: 1 hours
suppression_enabled: true
suppression_fields:
  - xdm.source.ipv4
  - xdm.target.user.username
xql_query: |
  datamodel dataset = {dataset}
  | filter xdm.event.type = "AUTHENTICATION" and xdm.event.outcome = "FAILED"
  | fields xdm.event.type, xdm.event.outcome, xdm.source.ipv4, xdm.source.host.hostname, xdm.target.user.username, xdm.source.user.username
"""

        rule_filename = rule_name.replace(" ", "_").replace("-", "_")
        rule_path = rules_dir / f"{rule_filename}.yml"
        with open(rule_path, "w", encoding="utf-8") as f:
            f.write(rule_yml)

    def _create_parsing_rule(self, pack_path: Path, pack_name: str) -> None:
        """Create sample parsing rule for Cortex Platform.
        
        Follows the demisto-sdk parsingrule.yml schema. The rules and samples
        fields are empty strings as the SDK unifies them automatically.
        Based on working examples from demisto/content repository.
        """
        rules_dir = pack_path / "ParsingRules" / f"{pack_name}ParsingRules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        rule_id = f"{pack_name} Parsing Rule"
        rule_file_base = f"{pack_name}ParsingRules"
        vendor = pack_name.lower()
        dataset = f"{vendor}_raw"

        rule_yml = f"""id: {rule_id}
name: {pack_name} Parsing Rule
fromversion: 6.10.0
tags: []
rules: ''
samples: ''
"""

        xif_content = f"""[INGEST:vendor="{pack_name}", product="{pack_name}", target_dataset="{dataset}", no_hit=keep]
filter _raw_log ~= "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}"
| alter
    tmp_timestamp = arrayindex(regextract(_raw_log, "(\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*)"), 0),
    hostname = arrayindex(regextract(_raw_log, "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*\\s+(\\S+)"), 0),
    process_name = arrayindex(regextract(_raw_log, "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*\\s+\\S+\\s+(\\w+)"), 0),
    message = arrayindex(regextract(_raw_log, "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*\\s+\\S+\\s+\\w+[:\\s]+(.*)$"), 0)
| alter
    _time = if(tmp_timestamp ~= "\\.", parse_timestamp("%Y-%m-%dT%H:%M:%E3SZ", tmp_timestamp), parse_timestamp("%Y-%m-%dT%H:%M:%SZ", tmp_timestamp))
| fields -tmp_timestamp;
"""

        with open(rules_dir / f"{rule_file_base}.yml", "w", encoding="utf-8") as f:
            f.write(rule_yml)

        with open(rules_dir / f"{rule_file_base}.xif", "w", encoding="utf-8") as f:
            f.write(xif_content)

    def _create_modeling_rule(self, pack_path: Path, pack_name: str) -> None:
        """Create sample modelling rule for Cortex Platform.
        
        Follows the demisto-sdk modelingrule.yml schema. The rules and schema
        fields are empty strings as the SDK unifies them automatically.
        Based on working VMwareESXi example from demisto/content repository.
        """
        rules_dir = pack_path / "ModelingRules" / f"{pack_name}ModelingRules"
        rules_dir.mkdir(parents=True, exist_ok=True)

        rule_file_base = f"{pack_name}ModelingRules"
        vendor = pack_name.lower()
        dataset = f"{vendor}_raw"

        rule_yml = f"""fromversion: 6.10.0
id: {pack_name}
name: {pack_name} Modeling Rule
rules: ''
schema: ''
tags: {pack_name}
"""

        xif_content = f"""[MODEL: dataset="{dataset}"]
alter
    event_type = arrayindex(regextract(_raw_log, "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*\\s+\\S+\\s+(\\w+)"), 0),
    username = arrayindex(regextract(_raw_log, "user[=:\\s]+(\\S+)"), 0),
    source_ip = arrayindex(regextract(_raw_log, "from\\s+(\\d+\\.\\d+\\.\\d+\\.\\d+)"), 0),
    source_port = arrayindex(regextract(_raw_log, "port\\s+(\\d+)"), 0),
    message = arrayindex(regextract(_raw_log, "\\d{{4}}-\\d{{2}}-\\d{{2}}T\\d{{2}}:\\d{{2}}:\\d{{2}}[Z\\d\\.]*\\s+\\S+\\s+\\w+[:\\s]+(.*)$"), 0)
| alter
    xdm.event.type = event_type,
    xdm.source.user.username = username,
    xdm.source.ipv4 = source_ip,
    xdm.source.port = to_number(source_port),
    xdm.event.description = message;
"""

        schema_json = f"""{{
  "{dataset}": {{
    "_raw_log": {{
      "type": "string",
      "is_array": false
    }}
  }}
}}
"""

        with open(rules_dir / f"{rule_file_base}.yml", "w", encoding="utf-8") as f:
            f.write(rule_yml)

        with open(rules_dir / f"{rule_file_base}.xif", "w", encoding="utf-8") as f:
            f.write(xif_content)

        with open(rules_dir / f"{rule_file_base}_schema.json", "w", encoding="utf-8") as f:
            f.write(schema_json)

    def _create_release_notes(self, pack_path: Path, pack_name: str) -> None:
        """Create ReleaseNotes folder with initial version file.
        
        Creates a 1_0_0.md file documenting the initial release.
        """
        notes_dir = pack_path / "ReleaseNotes"
        notes_dir.mkdir(exist_ok=True)

        release_content = f"""#### Parsing Rules

##### {pack_name} Parsing Rule

- Initial release of {pack_name} parsing rules.

#### Modeling Rules

##### {pack_name} Modeling Rule

- Initial release of {pack_name} modelling rules for XDM mapping.

#### Correlation Rules

##### {pack_name} - Multiple Failed Login Attempts

- Initial release of brute force detection correlation rule.

#### XSIAM Dashboards

##### {pack_name} Example

- Initial release of example dashboard.

#### XSIAM Reports

##### {pack_name} Example

- Initial release of example report.
"""

        with open(notes_dir / "1_0_0.md", "w", encoding="utf-8") as f:
            f.write(release_content)

    def _create_xsiam_dashboard(self, pack_path: Path, pack_name: str) -> None:
        """Create sample XSIAM dashboard for Cortex Platform.
        
        Creates an example dashboard JSON file that can be uploaded to XSIAM.
        The dashboard includes a header and sample widgets.
        Structure matches the format exported from XSIAM Dashboard Manager.
        """
        dashboards_dir = pack_path / "XSIAMDashboards"
        dashboards_dir.mkdir(exist_ok=True)
        
        dashboard_id = f"{pack_name.lower()}_example_dashboard"
        dashboard_name = f"{pack_name} Example"
        
        dashboard_data = {
            "dashboards_data": [
                {
                    "name": dashboard_name,
                    "description": f"An example dashboard for {pack_name}",
                    "status": "ENABLED",
                    "layout": [
                        {
                            "id": "row-header",
                            "data": [
                                {
                                    "key": "header",
                                    "data": {
                                        "name": dashboard_name,
                                        "type": "",
                                        "width": 100,
                                        "height": 250,
                                        "description": f"An example dashboard for {pack_name}"
                                    }
                                }
                            ]
                        }
                    ],
                    "global_id": dashboard_id,
                    "metadata": {"params": []}
                }
            ],
            "widgets_data": [],
            "id": dashboard_id,
            "name": dashboard_name
        }
        
        dashboard_path = dashboards_dir / f"{pack_name}ExampleDashboard.json"
        with open(dashboard_path, "w", encoding="utf-8") as f:
            json.dump(dashboard_data, f, indent=2)
            f.write("\n")
    
    def _create_xsiam_report(self, pack_path: Path, pack_name: str) -> None:
        """Create sample XSIAM report for Cortex Platform.
        
        Creates an example report JSON file that can be uploaded to XSIAM.
        The report includes a header and sample layout.
        Structure matches the format exported from XSIAM Report Templates.
        """
        reports_dir = pack_path / "XSIAMReports"
        reports_dir.mkdir(exist_ok=True)
        
        report_id = f"{pack_name.lower()}_example_report"
        report_name = f"{pack_name} Example"
        
        report_data = {
            "templates_data": [
                {
                    "report_name": report_name,
                    "report_description": f"An example report for {pack_name}",
                    "layout": [
                        {
                            "id": "row-header",
                            "data": [
                                {
                                    "key": "header",
                                    "data": {
                                        "name": report_name,
                                        "type": "",
                                        "width": 100,
                                        "height": 250,
                                        "description": f"An example report for {pack_name}"
                                    }
                                }
                            ]
                        }
                    ],
                    "default_template_id": None,
                    "time_frame": {"relativeTime": 86400000},
                    "global_id": report_id,
                    "time_offset": 0,
                    "metadata": "{\"params\": []}"
                }
            ],
            "widgets_data": [],
            "id": report_id,
            "name": report_name
        }
        
        report_path = reports_dir / f"{pack_name}ExampleReport.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
            f.write("\n")

    def create_xsiam_content(self, pack_path: Path, pack_name: str) -> None:
        """Create Cortex Platform content structure.
        
        Creates complete XSIAM content including ParsingRules, ModelingRules,
        CorrelationRules, XSIAMDashboards, XSIAMReports, and ReleaseNotes.
        All templates follow the official demisto-sdk schemas and are based
        on working examples from the demisto/content repository.
        """
        self._create_parsing_rule(pack_path, pack_name)
        self._create_modeling_rule(pack_path, pack_name)
        self._create_correlation_rule(pack_path, pack_name)
        self._create_xsiam_dashboard(pack_path, pack_name)
        self._create_xsiam_report(pack_path, pack_name)
        self._create_release_notes(pack_path, pack_name)

    def list_templates(self) -> List[str]:
        """List available pack templates."""
        return ["default", "integration", "playbook", "minimal"]

    def create_from_template(
        self,
        template_name: str,
        pack_name: str,
        description: str = ""
    ) -> Path:
        """
        Create a pack from a predefined template.

        Args:
            template_name: Name of the template to use.
            pack_name: Name of the pack.
            description: Pack description.

        Returns:
            Path to the created pack.
        """
        templates = {
            "default": self.CONTENT_DIRECTORIES,
            "integration": ["Integrations", "TestPlaybooks"],
            "playbook": ["Playbooks", "Scripts"],
            "minimal": []
        }

        directories = templates.get(template_name, self.CONTENT_DIRECTORIES)
        return self.create_pack(
            pack_name,
            description,
            create_directories=directories
        )
