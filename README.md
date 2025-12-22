<p align="center">
  <img src="assets/spellbook-logo.png" alt="GoCortex Spellbook" width="600">
</p>

# GoCortex Spellbook

A Python toolset for building, validating, and packaging Cortex Platform content packs.

## Overview

GoCortex Spellbook is a toolset for building, validating, and packaging Cortex Platform content packs. It solves the problem of creating compliant content packs without needing to understand the intricacies of the demisto-sdk and Cortex Platform schema requirements.

What it does:

- Creates new content pack instances with correct structure
- Generates XSIAM content templates (CorrelationRules, ParsingRules, ModelingRules)
- Validates content against Cortex Platform schemas using demisto-sdk
- Packages content into uploadable zip files
- Uploads content directly to Cortex Platform instances

Why it exists:

The demisto-sdk is powerful but complex. Spellbook wraps it in a simpler interface and provides working templates that have been verified to upload successfully.

## Features

- Instance initialisation with optional GitHub Actions templates
- Multi-pack support within a single content instance
- Content renaming to fix naming mismatches after copying packs
- Validation and linting using demisto-sdk
- Automated packaging into distributable zip files
- Direct upload to Cortex Platform instances

## Workflow Guides

Choose your preferred method and follow the corresponding guide:

| Method | Best For | Guide |
|--------|----------|-------|
| Docker (Local) | Most users. No Python setup required. | [README_LOCAL-DOCKER.md](README_LOCAL-DOCKER.md) |
| Source (Local) | Developers who want to modify Spellbook. | [README_SOURCE.md](README_SOURCE.md) |
| CI/CD | Automated builds triggered by Git tags. | [README_CICD.md](README_CICD.md) |

## Quick Start (Docker)

```bash
# Pull from GitHub Container Registry (preferred)
docker pull ghcr.io/gocortexio/spellbook:latest

# Or build locally from source
docker build -t ghcr.io/gocortexio/spellbook .

# Create a content instance
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook init my-content --author "My Organisation"

# Initialise Git (required for validation)
cd my-content
git init
git add .
git commit -s -m "Initial commit"

# Build all packs
docker run --rm -v $(pwd):/content ghcr.io/gocortexio/spellbook build --all
```

## Commands

| Command | Description |
|---------|-------------|
| init | Create a new content instance with starter pack |
| create | Create a new pack from template |
| rename-content | Rename content items to match pack name |
| list-packs | List all discovered packs |
| validate | Validate a pack using demisto-sdk |
| validate-all | Validate all packs |
| lint | Lint a pack using demisto-sdk pre-commit |
| build | Build and package packs |
| upload | Upload a pack to Cortex Platform |
| version | Show version information for a pack |
| set-version | Set a specific version for a pack |
| bump-version | Automatically increment pack version |

## Instance Structure

After running `init`, your instance has this structure:

```
my-content/
|-- .github/workflows/      # CI/CD pipelines (if enabled)
|   |-- conjure.yml          # Builds packs on version tags
|   +-- validate.yml        # Validates packs on PRs
|-- Packs/
|   +-- SamplePack/         # Starter pack with examples
|       |-- pack_metadata.json
|       |-- README.md
|       |-- CorrelationRules/
|       |-- ParsingRules/
|       +-- ModelingRules/
|-- artifacts/              # Built zip files (gitignored)
+-- spellbook.yaml          # Build configuration
```

## Configuration

Each instance has a `spellbook.yaml` file:

```yaml
packs_directory: Packs
artifacts_directory: artifacts

defaults:
  support: community
  author: "Your Organisation"
  marketplaces:
    - xsoar
    - marketplacev2

exclude_packs: []

validation:
  enabled: true
  allow_warnings: true

packaging:
  create_zip: true
```

## Version Management

Pack versions are stored in `pack_metadata.json` within each pack. Use these commands to manage versions:

```bash
# Show current version
gocortex-spellbook version SamplePack

# Set a specific version
gocortex-spellbook set-version SamplePack 2.0.0

# Increment revision (1.0.0 -> 1.0.1) - default behaviour
gocortex-spellbook bump-version SamplePack

# Increment revision explicitly (1.0.0 -> 1.0.1)
gocortex-spellbook bump-version SamplePack --revision

# Increment minor version (1.0.0 -> 1.1.0)
gocortex-spellbook bump-version SamplePack --minor

# Increment major version (1.0.0 -> 2.0.0)
gocortex-spellbook bump-version SamplePack --major

# Bump version and create Git tag for CI/CD
gocortex-spellbook bump-version SamplePack --tag
```

The `--tag` flag creates a Git tag in the format `PackName-v1.0.1` which triggers CI/CD builds when pushed. Use `git push origin PackName-v1.0.1` after tagging.

## Licence

This project is available under the MIT Licence.

## References

- Cortex Platform Content Pack Format: https://xsoar.pan.dev/docs/packs/packs-format
- Demisto SDK Documentation: https://docs-cortex.paloaltonetworks.com/r/1/Demisto-SDK-Guide
