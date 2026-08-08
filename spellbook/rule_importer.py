# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Shared Rule Importer Base

Behaviour common to the parsing and modelling rule importers: writing files
into a pack without letting a crafted name escape it, and turning a dataset
or user-supplied name into a package stem.

Both rule types are file sets bound by filename stem, so the two importers
differ only in which files they emit, which header they read, and which
suffix the SDK requires. Everything else lives here so a fix to the path
handling reaches both.
"""

import re
from pathlib import Path


class RuleImporterBase:
    """Common file-writing and naming behaviour for rule importers."""

    def __init__(self, packs_dir: Path):
        """
        Initialise the importer.

        Args:
            packs_dir: Path to the Packs directory.
        """
        self.packs_dir = packs_dir

    def _validate_stem(self, stem: str, required_suffix: str, validator: str) -> None:
        """Reject a stem that is unsafe as a path segment or fails the SDK.

        Args:
            stem: Candidate package stem.
            required_suffix: Suffix the content type's id must carry.
            validator: demisto-sdk validator id, for the error message.
        """
        if not stem:
            raise ValueError("Package stem is empty")
        if stem in (".", ".."):
            raise ValueError(f"Package stem is a path traversal segment: {stem!r}")
        if "/" in stem or "\\" in stem:
            raise ValueError(f"Package stem contains a path separator: {stem!r}")
        if Path(stem).is_absolute():
            raise ValueError(f"Package stem is an absolute path: {stem!r}")
        if not stem.endswith(required_suffix):
            raise ValueError(
                f"Package stem '{stem}' must end with '{required_suffix}' "
                f"(demisto-sdk validator {validator})"
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

    def _normalise_line_endings(self, value: str) -> str:
        """Normalise CRLF and CR to LF.

        Console paste frequently carries Windows line endings.
        """
        return value.replace("\r\n", "\n").replace("\r", "\n")
