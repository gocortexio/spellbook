"""
Instance Module

Creates and manages user content instances with their own Git structure.
"""

import os
import shutil
from pathlib import Path
from typing import Optional

import yaml


class InstanceManager:
    """Manages user content instances."""

    DEFAULT_WORKSPACE_NAME = "content"

    def __init__(self, base_path: str = "."):
        """
        Initialise the instance manager.

        Args:
            base_path: Base path where Spellbook is installed.
        """
        self.base_path = Path(base_path)
        self.templates_path = self.base_path / "templates"

    def create_instance(
        self,
        name: str,
        author: str = "",
        description: str = "",
        include_ci: bool = True
    ) -> Path:
        """
        Create a new user instance for content development.

        Args:
            name: Name of the instance folder.
            author: Default author for packs.
            description: Description of the instance.
            include_ci: Whether to include GitHub Actions workflows.

        Returns:
            Path to the created instance.
        """
        instance_path = self.base_path / name

        if instance_path.exists():
            raise FileExistsError(
                f"Instance '{name}' already exists at {instance_path}"
            )

        instance_path.mkdir(parents=True)

        self._create_packs_directory(instance_path)

        if include_ci:
            self._create_github_workflows(instance_path)

        self._create_spellbook_config(instance_path, author)

        self._create_gitignore(instance_path)

        self._create_readme(instance_path, name, description, include_ci)

        self._create_sample_pack(instance_path, author)

        return instance_path

    def _create_packs_directory(self, instance_path: Path) -> None:
        """Create the Packs directory."""
        packs_dir = instance_path / "Packs"
        packs_dir.mkdir()

    def _create_github_workflows(self, instance_path: Path) -> None:
        """Copy GitHub workflow templates to instance."""
        workflows_dir = instance_path / ".github" / "workflows"
        workflows_dir.mkdir(parents=True)

        build_workflow = '''name: Build Content Packs

on:
  push:
    tags:
      - '*-v*'
  workflow_dispatch:
    inputs:
      pack_name:
        description: 'Pack name to build (leave blank for all packs)'
        required: false
        default: ''

jobs:
  build:
    name: Build Pack
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Build packs
        run: |
          docker run --rm \\
            -v ${{ github.workspace }}/Packs:/content/Packs \\
            -v ${{ github.workspace }}/artifacts:/content/artifacts \\
            -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \\
            ghcr.io/gocortexio/spellbook:latest \\
            build --all --no-validate

      - name: Upload artefacts
        uses: actions/upload-artifact@v4
        with:
          name: content-packs
          path: artifacts/*.zip
          retention-days: 30

  release:
    name: Create Release
    needs: build
    runs-on: ubuntu-latest
    if: startsWith(github.ref, 'refs/tags/')
    permissions:
      contents: write
    steps:
      - name: Download artefacts
        uses: actions/download-artifact@v4
        with:
          name: content-packs
          path: release-artifacts

      - name: Create release
        uses: softprops/action-gh-release@v2
        with:
          files: release-artifacts/*.zip
          generate_release_notes: true
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
'''
        conjure_path = workflows_dir / "conjure.yml"
        with open(conjure_path, "w", encoding="utf-8") as f:
            f.write(build_workflow)

        validate_workflow = '''name: Validate Content Packs

on:
  pull_request:
    paths:
      - 'Packs/**'
  push:
    branches:
      - main
      - master
    paths:
      - 'Packs/**'

jobs:
  validate:
    name: Validate Packs
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Validate packs
        run: |
          docker run --rm \\
            -v ${{ github.workspace }}/Packs:/content/Packs \\
            -v ${{ github.workspace }}/spellbook.yaml:/content/spellbook.yaml \\
            ghcr.io/gocortexio/spellbook:latest \\
            validate-all

      - name: Check validation results
        run: |
          echo "Validation complete"
'''
        validate_path = workflows_dir / "validate.yml"
        with open(validate_path, "w", encoding="utf-8") as f:
            f.write(validate_workflow)

    def _create_spellbook_config(
        self,
        instance_path: Path,
        author: str
    ) -> None:
        """Create spellbook.yaml configuration file."""
        config = {
            "packs_directory": "Packs",
            "artifacts_directory": "artifacts",
            "defaults": {
                "support": "community",
                "author": author or "Your Organisation",
                "url": "",
                "email": "",
                "categories": [],
                "tags": [],
                "useCases": [],
                "keywords": [],
                "marketplaces": ["xsoar", "marketplacev2"]
            },
            "exclude_packs": [],
            "validation": {
                "enabled": True,
                "allow_warnings": True
            },
            "linting": {
                "enabled": True,
                "run_tests": True
            },
            "packaging": {
                "create_zip": True
            }
        }

        config_path = instance_path / "spellbook.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    def _create_gitignore(self, instance_path: Path) -> None:
        """Create .gitignore for the instance."""
        gitignore_content = '''# Build artefacts
artifacts/
*.zip

# Python
__pycache__/
*.py[cod]
*.so
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db

# Demisto SDK
.demisto-sdk-conf
CommonServerPython/
CommonServerUserPython/
demistomock.py

# Testing
.pytest_cache/
.coverage
htmlcov/
'''
        gitignore_path = instance_path / ".gitignore"
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(gitignore_content)

    def _create_readme(
        self,
        instance_path: Path,
        name: str,
        description: str,
        include_ci: bool = True
    ) -> None:
        """Create README.md for the instance."""
        ci_structure = """|-- .github/workflows/      # CI/CD pipelines
""" if include_ci else ""

        ci_section = """
## GitHub Actions

This repository includes GitHub Actions workflows for automated builds and validation.

Before using the workflows, update the Docker image reference in `.github/workflows/conjure.yml`
and `.github/workflows/validate.yml` to point to your published Spellbook image.

### Version Tagging

Create Git tags to trigger releases:

```bash
git tag PackName-v1.0.0
git push origin PackName-v1.0.0
```
""" if include_ci else ""

        readme_content = f'''# {name}

{description or "Cortex Platform content packs repository."}

## Overview

This repository contains Cortex Platform content packs built using GoCortex Spellbook.

## Structure

```
{name}/
|-- Packs/                  # Content packs
|   +-- SamplePack/         # Starter pack with examples
|       |-- pack_metadata.json
|       |-- README.md
|       |-- Integrations/
|       |-- Scripts/
|       +-- Playbooks/
{ci_structure}|-- artifacts/              # Built pack zip files
+-- spellbook.yaml          # Build configuration
```

## Building Packs

Build packs locally using Docker. The built zip files appear in the `artifacts/` directory.

```bash
# Build all packs (run from this directory)
docker run --rm -v $(pwd):/content gocortex-spellbook build --all

# Build a specific pack
docker run --rm -v $(pwd):/content gocortex-spellbook build SamplePack

# The zip files are created in artifacts/
ls artifacts/
```

## Creating a New Pack

```bash
docker run --rm -v $(pwd):/content gocortex-spellbook create MyNewPack --description "My new pack"
```

## Validating Packs

```bash
# Validate all packs
docker run --rm -v $(pwd):/content gocortex-spellbook validate-all

# Validate a specific pack
docker run --rm -v $(pwd):/content gocortex-spellbook validate SamplePack
```
{ci_section}
## Uploading to Cortex Platform

After building, upload the zip files from `artifacts/` to your Cortex Platform tenant:

```bash
docker run --rm -v $(pwd):/content \\
  -e DEMISTO_BASE_URL \\
  -e DEMISTO_API_KEY \\
  -e XSIAM_AUTH_ID \\
  gocortex-spellbook upload Packs/SamplePack --zip --xsiam
```

## References

- Cortex Platform Content Pack Format: https://xsoar.pan.dev/docs/packs/packs-format
'''
        readme_path = instance_path / "README.md"
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme_content)

    def _create_sample_pack(self, instance_path: Path, author: str = "") -> None:
        """Create a sample pack in the instance."""
        from .pack_template import PackTemplate

        packs_dir = instance_path / "Packs"

        template = PackTemplate.__new__(PackTemplate)
        template.config = {}
        template.packs_dir = packs_dir
        template.defaults = {
            "support": "community",
            "author": author or "Your Organisation",
            "url": "",
            "email": "",
            "categories": [],
            "tags": [],
            "useCases": [],
            "keywords": [],
            "marketplaces": ["xsoar", "marketplacev2"]
        }

        pack_path = template.create_pack(
            "SamplePack",
            "A sample content pack to get you started.",
            create_directories=None
        )

        template.create_xsiam_content(pack_path, "SamplePack")

    def list_instances(self) -> list:
        """
        List all instances in the base path.

        Returns:
            List of instance names.
        """
        instances = []
        for item in self.base_path.iterdir():
            if item.is_dir():
                if (item / "spellbook.yaml").exists():
                    if (item / "Packs").exists():
                        instances.append(item.name)
        return instances
