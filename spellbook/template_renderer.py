# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Template Renderer Module

Renders content pack artefacts from self-describing template files.
Templates declare their own placeholder tokens, using two sigils:

  %%TOKEN%%   user-supplied tokens (via --set or interactive prompts)
  @@TOKEN@@   auto-derived tokens filled in by the renderer itself
              (e.g. TEMPLATE_HASH, TASK_UUID_<n>)

The sigil alone determines whether a token is user-supplied or
auto-derived; no Python allow-list is consulted. Template subfolders
map 1:1 to content type directories in a pack (Playbooks/, Triggers/,
Jobs/, etc.).
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

import yaml


BUILTIN_TEMPLATES_DIR = Path(__file__).parent / "templates"
TOKEN_PATTERN = re.compile(r"%%([A-Z_][A-Z0-9_]*)%%")
AUTO_TOKEN_PATTERN = re.compile(r"@@([A-Z_][A-Z0-9_]*)@@")
REPLACEMENT_CHAR = "?"
JUNK_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}

PACK_IGNORE_TEMPLATE_NAME = "pack-ignore.template"
PACK_IGNORE_FILE = ".pack-ignore"

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

# Content types that demisto-sdk only recognises when the output filename
# carries a specific prefix. Source of truth: demisto-sdk's filename regex
# map in demisto_sdk/commands/common/constants.py — e.g. JOB_JSON_REGEX is
# r"{JOBS_DIR_REGEX}\/job-([^/]+)\.json", so a Job whose file is not named
# job-<something>.json is silently skipped by the uploader. Other content
# types we currently ship (Playbooks, Triggers, ModelingRules, etc.) use
# permissive regexes and need no prefix here.
CONTENT_TYPE_FILENAME_PREFIXES = {"Jobs": "job-"}


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

    def _iter_template_files(self):
        """Yield non-symlink template files that resolve within template_dir.

        Used by token discovery methods to ensure no symlinked or out-of-bounds
        files are read during scanning.
        """
        resolved_root = self.template_dir.resolve()
        for path in self.template_dir.rglob("*"):
            if path.is_symlink():
                continue
            if not path.is_file():
                continue
            if path.name in JUNK_FILES:
                continue
            try:
                path.resolve().relative_to(resolved_root)
            except ValueError:
                continue
            yield path

    def discover_tokens(self) -> list[str]:
        """Scan all template files and return user-facing token names.

        Only the %% sigil is scanned; @@ auto-tokens are excluded
        structurally. Tokens derived from .xql filenames are internal
        and excluded from the returned list.
        """
        tokens = set()
        xql_tokens = self._discover_xql_tokens()
        for path in self._iter_template_files():
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            tokens.update(TOKEN_PATTERN.findall(content))
        return sorted(tokens - xql_tokens)

    def discover_auto_tokens(self) -> list[str]:
        """Scan all template files and return auto-derived token names.

        Only the @@ sigil is scanned. These tokens are filled in by
        the caller (e.g. ``summon_template``) and must never be
        supplied by the user via ``--set``.
        """
        tokens = set()
        for path in self._iter_template_files():
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            tokens.update(AUTO_TOKEN_PATTERN.findall(content))
        return sorted(tokens)

    def _discover_xql_tokens(self) -> set[str]:
        """Return the set of internal token names derived from .xql filenames."""
        resolved_root = self.template_dir.resolve()
        xql_tokens = set()
        for xql_path in self.template_dir.rglob(f"*{XQL_EXTENSION}"):
            if xql_path.is_symlink():
                continue
            try:
                xql_path.resolve().relative_to(resolved_root)
            except ValueError:
                continue
            xql_tokens.add(xql_path.stem)
        return xql_tokens

    def discover_content_types(self) -> list[str]:
        """Return content type subfolders present in this template."""
        types = []
        for entry in sorted(self.template_dir.iterdir()):
            if entry.name not in CONTENT_TYPE_DIRS:
                continue
            if entry.is_symlink():
                raise ValueError(
                    f"Template content-type directory '{entry.name}' is a symlink; "
                    f"refusing to read through it to prevent path escape"
                )
            if entry.is_dir():
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
        missing += [t for t in self.discover_auto_tokens() if t not in values]
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

        self._apply_pack_ignore_fragment(values, pack_dir)

        return results

    def _apply_pack_ignore_fragment(
        self, values: dict[str, str], pack_dir: Path
    ) -> None:
        """Merge an optional pack-ignore fragment into the pack's .pack-ignore.

        If the template root contains a ``pack-ignore.template`` file, its
        contents are token-rendered and appended to the destination pack's
        ``.pack-ignore``. Stanzas that already exist verbatim are skipped so
        re-running summon stays byte-identical.
        """
        fragment_path = self.template_dir / PACK_IGNORE_TEMPLATE_NAME
        if not fragment_path.exists():
            return
        if fragment_path.is_symlink():
            raise ValueError(
                f"Template file '{PACK_IGNORE_TEMPLATE_NAME}' is a symlink; "
                f"refusing to read through it to prevent path escape"
            )
        if not fragment_path.is_file():
            return

        try:
            raw = fragment_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(
                _format_encoding_error(
                    fragment_path, self.template_name, "(root)", e
                )
            ) from None

        rendered = self._replace_tokens(raw, values).strip()
        if not rendered:
            return

        target = pack_dir / PACK_IGNORE_FILE
        if target.is_symlink():
            raise ValueError(
                f"Pack file '{PACK_IGNORE_FILE}' is a symlink; "
                f"refusing to read or write through it to prevent path escape"
            )
        resolved_target = target.resolve()
        resolved_pack = pack_dir.resolve()
        try:
            resolved_target.relative_to(resolved_pack)
        except ValueError:
            raise ValueError(
                f"Pack file '{PACK_IGNORE_FILE}' resolves outside pack directory "
                f"'{pack_dir}'; refusing to read or write"
            )
        existing = target.read_text(encoding="utf-8") if target.exists() else ""

        new_blocks = []
        for block in re.split(r"\n\s*\n", rendered):
            block = block.strip()
            if block and block not in existing:
                new_blocks.append(block)

        if not new_blocks:
            return

        suffix = "\n\n".join(new_blocks) + "\n"
        if existing and not existing.endswith("\n"):
            existing += "\n"
        if existing and not existing.endswith("\n\n"):
            existing += "\n"
        target.write_text(existing + suffix, encoding="utf-8")

    def _render_content_type(
        self,
        content_type: str,
        values: dict[str, str],
        pack_dir: Path,
    ) -> list[dict]:
        """Render all template files for a single content type."""
        source_dir = self.template_dir / content_type
        resolved_source_dir = source_dir.resolve()
        results = []

        xql_snippets: dict[str, str] = {}
        for xql_file in sorted(source_dir.glob(f"*{XQL_EXTENSION}")):
            if xql_file.is_symlink():
                raise ValueError(
                    f"Template file '{xql_file.name}' in "
                    f"'{self.template_name}/{content_type}' is a symlink; "
                    f"refusing to read through it to prevent path escape"
                )
            try:
                xql_file.resolve().relative_to(resolved_source_dir)
            except ValueError:
                raise ValueError(
                    f"Template file '{xql_file.name}' in "
                    f"'{self.template_name}/{content_type}' resolves outside "
                    f"the template directory; refusing to read it"
                )
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

        for template_file in sorted(source_dir.rglob("*")):
            if not template_file.is_file():
                continue
            if template_file.suffix == XQL_EXTENSION:
                continue
            if template_file.name in JUNK_FILES:
                continue

            if template_file.is_symlink():
                raise ValueError(
                    f"Template file '{template_file.name}' in "
                    f"'{self.template_name}/{content_type}' is a symlink; "
                    f"refusing to read through it to prevent path escape"
                )
            try:
                template_file.resolve().relative_to(resolved_source_dir)
            except ValueError:
                raise ValueError(
                    f"Template file '{template_file.name}' in "
                    f"'{self.template_name}/{content_type}' resolves outside "
                    f"the template directory; refusing to read it"
                )

            rel_parent = template_file.parent.relative_to(source_dir)
            rendered_parts = []
            for part in rel_parent.parts:
                rendered = self._replace_tokens(part, values)
                self._validate_path_segment(rendered, context=f"token-expanded directory '{part}'")
                rendered_parts.append(rendered)
            rendered_subdir = Path(*rendered_parts) if rendered_parts else Path()

            result = self._render_file(
                template_file,
                content_type,
                values,
                pack_dir,
                xql_snippets,
                rendered_subdir,
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
        rendered_subdir: Path = Path(),
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
            try:
                data = json.loads(output_content)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"File '{template_file.name}' in "
                    f"'{self.template_name}/{content_type}' is not valid JSON: {e}"
                ) from None
            if isinstance(data, dict) and isinstance(data.get("name"), str):
                name = data["name"]
                filename = self._generate_filename(name, template_file.suffix)
            else:
                filename = self._replace_tokens(template_file.name, values)
                name = template_file.stem
        else:
            output_content = self._replace_tokens(raw_content, values)
            filename = self._replace_tokens(template_file.name, values)
            name = template_file.stem

        prefix = CONTENT_TYPE_FILENAME_PREFIXES.get(content_type)
        if prefix and not filename.startswith(prefix):
            filename = prefix + filename

        self._validate_path_segment(filename, context=f"rendered filename '{filename}'")

        output_dir = pack_dir / content_type / rendered_subdir

        self._assert_no_symlink_in_output_path(output_dir, pack_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / filename

        resolved_file = file_path.resolve()
        resolved_pack = pack_dir.resolve()
        try:
            resolved_file.relative_to(resolved_pack)
        except ValueError:
            raise ValueError(
                f"Output path '{file_path}' resolves outside pack directory "
                f"'{pack_dir}'; refusing to write"
            )

        overwritten = file_path.exists()
        file_path.write_text(output_content, encoding="utf-8")

        display_filename = (
            str(rendered_subdir / filename)
            if str(rendered_subdir) not in ("", ".")
            else filename
        )

        return {
            "content_type": content_type,
            "name": name,
            "filename": display_filename,
            "path": str(file_path),
            "overwritten": overwritten,
        }

    def _validate_path_segment(self, segment: str, context: str = "") -> None:
        """Raise ValueError if a token-expanded path segment is unsafe.

        Rejects empty segments, dotdot traversals, and segments that contain
        path separators or are absolute paths — all of which could cause
        writes to escape the intended pack directory.
        """
        if not segment:
            raise ValueError(
                f"Token expansion produced an empty path segment"
                + (f" ({context})" if context else "")
            )
        if segment in ("..", "."):
            raise ValueError(
                f"Token expansion produced a path traversal segment: {segment!r}"
                + (f" ({context})" if context else "")
            )
        if "/" in segment or "\\" in segment:
            raise ValueError(
                f"Token expansion produced a path separator in segment: {segment!r}"
                + (f" ({context})" if context else "")
            )
        if Path(segment).is_absolute():
            raise ValueError(
                f"Token expansion produced an absolute path segment: {segment!r}"
                + (f" ({context})" if context else "")
            )

    def _assert_no_symlink_in_output_path(self, output_dir: Path, root: Path) -> None:
        """Raise ValueError if any component of output_dir under root is a symlink.

        Walks each path component from root down to output_dir and rejects
        any component that is already a symlink, preventing writes from
        following an attacker-placed symlink to escape the pack directory.
        """
        try:
            rel = output_dir.relative_to(root)
        except ValueError:
            return
        current = root
        for part in rel.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(
                    f"Output path component '{current}' is a symlink; "
                    f"refusing to write through it to prevent path escape"
                )

    def _replace_tokens(self, text: str, values: dict[str, str]) -> str:
        """Replace %%TOKEN%% and @@TOKEN@@ placeholders in a string.

        Both sigils are resolved from the same ``values`` dict; only the
        spelling in the source template differs. XQL tokens (derived
        from .xql filenames, always %%) are left intact here; they are
        resolved separately by _insert_xql_token after YAML parsing.
        """
        xql_tokens = self._discover_xql_tokens()

        def user_replacer(match):
            token = match.group(1)
            if token in xql_tokens:
                return match.group(0)
            return values.get(token, match.group(0))

        def auto_replacer(match):
            token = match.group(1)
            return values.get(token, match.group(0))

        text = TOKEN_PATTERN.sub(user_replacer, text)
        text = AUTO_TOKEN_PATTERN.sub(auto_replacer, text)
        return text

    def _replace_tokens_in_dict(self, data: Any, values: dict[str, str]) -> None:
        """Recursively replace placeholder tokens in a dict structure."""
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
                # Filter OS junk so it never reaches a user's instance, even
                # if it is present in the source tree.
                shutil.copytree(
                    entry, dest, ignore=shutil.ignore_patterns(*JUNK_FILES)
                )
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
