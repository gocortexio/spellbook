# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
Version Manager Module

Handles automatic version detection and incrementing based on Git tags.
Supports pack-specific versioning using the pattern: {pack_name}-v{version}
"""

import re
import subprocess
from typing import Optional, Tuple


class VersionManager:
    """Manages pack versions based on Git tags."""

    DEFAULT_VERSION = "1.0.0"
    VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

    def __init__(self, tag_pattern: str = "{pack_name}-v{version}"):
        """
        Initialise the version manager.

        Args:
            tag_pattern: Pattern for Git tags containing pack name and version.
        """
        self.tag_pattern = tag_pattern

    def is_git_repository(self) -> bool:
        """
        Check if the current directory is within a Git repository.

        Returns:
            True if in a Git repository, False otherwise.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                check=True
            )
            return bool(result.stdout.strip())
        except subprocess.CalledProcessError:
            return False
        except FileNotFoundError:
            return False

    def get_git_tags(self) -> list:
        """
        Retrieve all Git tags from the repository.

        Returns:
            List of tag names sorted by version.
        """
        try:
            result = subprocess.run(
                ["git", "tag", "--list"],
                capture_output=True,
                text=True,
                check=True
            )
            tags = result.stdout.strip().split("\n")
            return [tag for tag in tags if tag]
        except subprocess.CalledProcessError:
            return []
        except FileNotFoundError:
            return []

    def parse_tag(self, tag: str, pack_name: str) -> Optional[str]:
        """
        Extract version from a tag for a specific pack.

        Args:
            tag: The Git tag to parse.
            pack_name: The name of the pack.

        Returns:
            Version string if tag matches pack, None otherwise.
        """
        prefix = f"{pack_name}-v"
        if tag.startswith(prefix):
            version = tag[len(prefix):]
            if self.VERSION_PATTERN.match(version):
                return version
        return None

    def get_latest_version(self, pack_name: str) -> str:
        """
        Get the latest version for a pack from Git tags.

        Args:
            pack_name: The name of the pack.

        Returns:
            Latest version string or default version if no tags found.
        """
        tags = self.get_git_tags()
        versions = []

        for tag in tags:
            version = self.parse_tag(tag, pack_name)
            if version:
                versions.append(version)

        if not versions:
            return self.DEFAULT_VERSION

        versions.sort(key=lambda v: self._version_tuple(v), reverse=True)
        return versions[0]

    def increment_version(
        self,
        version: str,
        increment_type: str = "revision"
    ) -> str:
        """
        Increment a version number.

        Args:
            version: Current version string (e.g., "1.0.0").
            increment_type: One of "major", "minor", or "revision".

        Returns:
            Incremented version string.
        """
        match = self.VERSION_PATTERN.match(version)
        if not match:
            return self.DEFAULT_VERSION

        major, minor, revision = map(int, match.groups())

        if increment_type == "major":
            major += 1
            minor = 0
            revision = 0
        elif increment_type == "minor":
            minor += 1
            revision = 0
        else:
            revision += 1

        return f"{major}.{minor}.{revision}"

    def get_next_version(
        self,
        pack_name: str,
        increment_type: str = "revision"
    ) -> str:
        """
        Calculate the next version for a pack.

        Args:
            pack_name: The name of the pack.
            increment_type: One of "major", "minor", or "revision".

        Returns:
            Next version string.
        """
        current = self.get_latest_version(pack_name)
        if current == self.DEFAULT_VERSION:
            tags = self.get_git_tags()
            pack_has_tags = any(
                self.parse_tag(tag, pack_name) for tag in tags
            )
            if not pack_has_tags:
                return self.DEFAULT_VERSION

        return self.increment_version(current, increment_type)

    def create_version_tag(self, pack_name: str, version: str) -> str:
        """
        Generate a Git tag string for a pack version.

        Args:
            pack_name: The name of the pack.
            version: The version string.

        Returns:
            Formatted Git tag string.
        """
        return f"{pack_name}-v{version}"

    def _version_tuple(self, version: str) -> Tuple[int, int, int]:
        """Convert version string to comparable tuple."""
        match = self.VERSION_PATTERN.match(version)
        if match:
            major, minor, revision = map(int, match.groups())
            return (major, minor, revision)
        return (0, 0, 0)
