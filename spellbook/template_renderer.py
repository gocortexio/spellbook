# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Template Renderer Module

Renders content pack artefacts from self-describing template files.
Templates declare their own placeholder tokens (%%TOKEN%%), and the
renderer discovers them at runtime. Template subfolders map 1:1 to
content type directories in a pack (Playbooks/, Triggers/, Jobs/, etc.).
"""

import re
import shutil
from pathlib import Path
from typing import Any

import yaml


BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"
TOKEN_PATTERN = re.compile(r"%%([A-Z_]+)%%")
REPLACEMENT_CHAR = "?"

CONTENT_TYPE_DIRS = {
    "Playbooks",
    "Triggers",
    "Jobs",
    "CorrelationRules",
    "ParsingRules",
    "ModelingRules",
    "XSIAMDashboards",
    "XSIAMReports",
    "XDRCTemplates",
    "Integrations",
    "Scripts",
    "IncidentTypes",
    "IncidentFields",
    "Layouts",
    "Classifiers",
}

XQL_EXTENSION = ".xql"


def _format_encoding_error(
    file_path: Path, template_name: str, content_type: str, err: UnicodeDecodeError
) -> str:
    """Build a human-readable error message for a UTF-8 decoding failure.

    Extracts the line number, column, and a snippet of the offending line
    with a caret marker pointing at the invalid byte.
    """
    raw = err.object
    pos = err.start
    bad_byte = raw[pos : pos + 1]

    before = raw[:pos]
    line_num = before.count(b"\n") + 1
    line_start = before.rfind(b"\n") + 1
    line_end = raw.find(b"\n", pos)
    if line_end == -1:
        line_end = len(raw)

    bad_line = raw[line_start:line_end].decode("utf-8", errors="replace")
    bad_line = bad_line.replace("\ufffd", REPLACEMENT_CHAR)

    prefix = raw[line_start:pos].decode("utf-8", errors="replace")
    prefix = prefix.replace("\ufffd", REPLACEMENT_CHAR)
    col = len(prefix) + 1
    marker = " " * (col - 1) + "^"

    return (
        f"File '{file_path.name}' in '{template_name}/{content_type}' "
        f"contains invalid encoding\n"
        f"  Line {line_num}, column {col}: "
        f"invalid byte 0x{bad_byte.hex()}\n"
        f"  {bad_line}\n"
        f"  {marker}"
    )


class TemplateRenderer:
    """Render content pack artefacts from template files."""

    def __init__(self, template_name: str, templates_dir: Path):
        self.template_name = template_name
        self.template_dir = templates_dir / template_name

        if not self.template_dir.is_dir():
            raise ValueError(f"Template not found: {template_name}")

    def discover_tokens(self) -> list[str]:
        """Scan all template files and return user-facing token names.

        Tokens derived from .xql filenames are internal and excluded
        from the returned list.
        """
        tokens = set()
        xql_tokens = self._discover_xql_tokens()
        for path in self.template_dir.rglob("*"):
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    continue
                tokens.update(TOKEN_PATTERN.findall(content))
        return sorted(tokens - xql_tokens)

    def _discover_xql_tokens(self) -> set[str]:
        """Return the set of internal token names derived from .xql filenames."""
        xql_tokens = set()
        for xql_path in self.template_dir.rglob(f"*{XQL_EXTENSION}"):
            xql_tokens.add(xql_path.stem)
        return xql_tokens

    def discover_content_types(self) -> list[str]:
        """Return content type subfolders present in this template."""
        types = []
        for entry in sorted(self.template_dir.iterdir()):
            if entry.is_dir() and entry.name in CONTENT_TYPE_DIRS:
                types.append(entry.name)
        return types

    def render(self, values: dict[str, str], pack_dir: Path) -> list[dict]:
        """Render template files and write artefacts to the pack directory.

        Args:
            values: Dict mapping token names to replacement values.
            pack_dir: Path to the target pack directory.

        Returns:
            List of result dicts with file paths and status.
        """
        missing = [t for t in self.discover_tokens() if t not in values]
        if missing:
            raise ValueError(
                f"Missing token(s): {', '.join(missing)}"
            )

        content_types = self.discover_content_types()
        if not content_types:
            raise ValueError(
                f"Template '{self.template_name}' has no content type subfolders"
            )

        results = []
        for content_type in content_types:
            type_results = self._render_content_type(
                content_type, values, pack_dir
            )
            results.extend(type_results)

        return results

    def _render_content_type(
        self,
        content_type: str,
        values: dict[str, str],
        pack_dir: Path,
    ) -> list[dict]:
        """Render all template files for a single content type."""
        source_dir = self.template_dir / content_type
        results = []

        xql_snippets: dict[str, str] = {}
        for xql_file in sorted(source_dir.glob(f"*{XQL_EXTENSION}")):
            token_name = xql_file.stem
            try:
                xql_raw = xql_file.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                raise ValueError(
                    _format_encoding_error(
                        xql_file, self.template_name, content_type, e
                    )
                ) from None
            xql_snippets[token_name] = self._replace_tokens(
                xql_raw, values
            ).strip()

        for template_file in sorted(source_dir.iterdir()):
            if not template_file.is_file():
                continue
            if template_file.suffix == XQL_EXTENSION:
                continue

            result = self._render_file(
                template_file, content_type, values, pack_dir, xql_snippets
            )
            results.append(result)

        return results

    def _render_file(
        self,
        template_file: Path,
        content_type: str,
        values: dict[str, str],
        pack_dir: Path,
        xql_snippets: dict[str, str],
    ) -> dict:
        """Render a single template file and write to the pack."""
        try:
            raw_content = template_file.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                _format_encoding_error(
                    template_file, self.template_name, content_type, e
                )
            ) from None

        if template_file.suffix in (".yml", ".yaml"):
            data = yaml.safe_load(raw_content)
            self._replace_tokens_in_dict(data, values)

            for token_name, xql_content in xql_snippets.items():
                if not self._insert_xql_token(data, token_name, xql_content):
                    raise ValueError(
                        f"Template file '{template_file.name}' has "
                        f"'{token_name}{XQL_EXTENSION}' but no "
                        f"%%{token_name}%% placeholder"
                    )

            name = data.get("name", template_file.stem)
            filename = self._generate_filename(name, template_file.suffix)
            output_content = self._to_yaml(data)
        elif template_file.suffix == ".json":
            output_content = self._replace_tokens(raw_content, values)
            filename = self._replace_tokens(template_file.name, values)
            name = template_file.stem
        else:
            output_content = self._replace_tokens(raw_content, values)
            filename = self._replace_tokens(template_file.name, values)
            name = template_file.stem

        output_dir = pack_dir / content_type
        output_dir.mkdir(exist_ok=True)
        file_path = output_dir / filename

        overwritten = file_path.exists()
        file_path.write_text(output_content, encoding="utf-8")

        return {
            "content_type": content_type,
            "name": name,
            "filename": filename,
            "path": str(file_path),
            "overwritten": overwritten,
        }

    def _replace_tokens(self, text: str, values: dict[str, str]) -> str:
        """Replace %%TOKEN%% placeholders in a string.

        XQL tokens (derived from .xql filenames) are left intact here;
        they are resolved separately by _insert_xql_token after YAML
        parsing.
        """
        xql_tokens = self._discover_xql_tokens()

        def replacer(match):
            token = match.group(1)
            if token in xql_tokens:
                return match.group(0)
            return values.get(token, match.group(0))

        return TOKEN_PATTERN.sub(replacer, text)

    def _replace_tokens_in_dict(self, data: Any, values: dict[str, str]) -> None:
        """Recursively replace %%TOKEN%% placeholders in a dict structure."""
        if isinstance(data, dict):
            for key in list(data.keys()):
                val = data[key]
                if isinstance(val, str):
                    data[key] = self._replace_tokens(val, values)
                elif isinstance(val, (dict, list)):
                    self._replace_tokens_in_dict(val, values)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, str):
                    data[i] = self._replace_tokens(item, values)
                elif isinstance(item, (dict, list)):
                    self._replace_tokens_in_dict(item, values)

    def _insert_xql_token(
        self, data: Any, token_name: str, xql_content: str
    ) -> bool:
        """Find and replace %%TOKEN_NAME%% placeholders with rendered XQL.

        Searches recursively through the data structure.
        Returns True if at least one placeholder was replaced.
        """
        placeholder = f"%%{token_name}%%"
        replaced = False
        if isinstance(data, dict):
            for key in list(data.keys()):
                val = data[key]
                if isinstance(val, str) and placeholder in val:
                    data[key] = xql_content
                    replaced = True
                elif isinstance(val, (dict, list)):
                    if self._insert_xql_token(val, token_name, xql_content):
                        replaced = True
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, str) and placeholder in item:
                    data[i] = xql_content
                    replaced = True
                elif isinstance(item, (dict, list)):
                    if self._insert_xql_token(item, token_name, xql_content):
                        replaced = True
        return replaced

    def _generate_filename(self, name: str, suffix: str = ".yml") -> str:
        """Generate a valid filename from the artefact name."""
        filename = name.replace(" - ", "___")
        filename = filename.replace(" ", "_")
        filename = re.sub(r"[^a-zA-Z0-9_\-]", "", filename)
        return f"{filename}{suffix}"

    def _to_yaml(self, data: dict) -> str:
        """Convert dictionary to YAML string with block style for multiline strings."""

        class TemplateDumper(yaml.SafeDumper):
            pass

        def str_representer(dumper, data):
            if "\n" in data:
                return dumper.represent_scalar(
                    "tag:yaml.org,2002:str", data, style="|"
                )
            return dumper.represent_scalar("tag:yaml.org,2002:str", data)

        TemplateDumper.add_representer(str, str_representer)

        return yaml.dump(
            data,
            Dumper=TemplateDumper,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )


def copy_builtin_templates(target_dir: Path) -> int:
    """Copy built-in templates to the instance templates directory.

    Args:
        target_dir: Path to the instance templates/ directory.

    Returns:
        Number of templates copied.
    """
    if not BUILTIN_TEMPLATES_DIR.is_dir():
        return 0

    target_dir.mkdir(exist_ok=True)
    count = 0

    for entry in sorted(BUILTIN_TEMPLATES_DIR.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            dest = target_dir / entry.name
            if not dest.exists():
                shutil.copytree(entry, dest)
                count += 1

    return count


def list_templates(templates_dir: Path) -> list[dict]:
    """List all available templates and their required tokens.

    Args:
        templates_dir: Path to the templates directory to scan.
    """
    if not templates_dir.is_dir():
        return []

    templates = []
    for entry in sorted(templates_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("_"):
            try:
                renderer = TemplateRenderer(entry.name, templates_dir)
                tokens = renderer.discover_tokens()
                content_types = renderer.discover_content_types()
                templates.append({
                    "name": entry.name,
                    "tokens": tokens,
                    "content_types": content_types,
                })
            except ValueError:
                pass
    return templates
