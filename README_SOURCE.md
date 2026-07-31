# GoCortex Spellbook - Local Python Workflow

GoCortex Spellbook is a toolset for building, validating, and packaging Cortex Platform content packs. It solves the problem of creating compliant content packs without needing to understand the intricacies of the demisto-sdk and Cortex Platform schema requirements.

This guide walks you through building Cortex Platform content packs by running Spellbook directly from Python source.

---

## Prerequisites

- Python 3.11 or later
- pip or uv package manager
- Git

---

## Clone Repository

Clone the Spellbook repository:

```bash
git clone <spellbook-repo-url>
cd gocortex-spellbook
```

---

## Install Dependencies

Using pip:

```bash
pip install "demisto-sdk==1.39.1" "gitpython>=3.1.50" "pyyaml>=6.0.3" "ruff==0.8.0"
```

Or using uv:

```bash
uv sync
```

Verify the installation:

```bash
python spellbook.py --help
```

---

## Run the Test Suite

The tests include contract and golden checks against the pinned demisto-sdk:
generated correlation, parsing, and modelling rules are validated against the
SDK's strict schemas, so schema drift fails the suite rather than a tenant
upload. The same suite runs in CI on every push and pull request.

```bash
pip install pytest
pytest
```

---

## Create a Content Instance

Run this command from the Spellbook directory:

```bash
python spellbook.py init my-content --author "Your Organisation"
```

This creates a my-content folder containing:

- Packs directory with a SamplePack to get you started
- spellbook.yaml configuration file
- GitHub Actions workflows (optional)

To skip GitHub Actions:

```bash
python spellbook.py init my-content --author "Your Organisation" --no-ci
```

---

## Initialise Git

A Git repository with at least one commit is required for demisto-sdk validation to work.

```bash
cd my-content
git init
git branch -M main
git add .
git commit -s -m "Initial commit"
```

If using a remote repository (optional):

```bash
git remote add origin <your-repo-url>
git push -u origin main
```

Return to the Spellbook directory for running commands:

```bash
cd ..
```

---

## Explore SamplePack

Your instance includes a SamplePack with example content. List the available packs:

```bash
python spellbook.py list-packs -c my-content/spellbook.yaml
```

The SamplePack contains starter templates for common content types including integrations, scripts, playbooks, and Cortex Platform content like modelling rules and parsing rules.

---

## Create a New Pack

[WARNING] Always use the create command to make new packs. Never copy existing packs directly, as this causes naming conflicts during upload.

```bash
python spellbook.py create MyNewPack -c my-content/spellbook.yaml --description "My new content pack"
```

This creates a properly structured pack with all required metadata files.

Options:

- `--author "Name"` sets the pack author. Without it, the author from `spellbook.yaml` `defaults.author` is used.
- `--template default|integration|playbook|minimal` selects which content directories are scaffolded.
- `--no-author-image` skips the placeholder author image.

By default `create` writes a placeholder `Author_image.png` (the GoCortexIO
wordmark) at the pack root, which demisto-sdk auto-detects as the pack's author
image. Replace it with your own branding, or pass `--no-author-image` to skip it.

---

## Import a Data Model Rule

Copy a data model (XDM) rule from the tenant rule editor, including its
`[MODEL: dataset="..."]` header, then pipe the XIF to the summon command:

```bash
cat rule.xif | python spellbook.py summon datamodel MyNewPack -c my-content/spellbook.yaml
```

This writes the three-file modelling rule package (`.yml`, `.xif`,
`_schema.json`) with matching filenames into `Packs/MyNewPack/ModelingRules/`.
The package is named after the dataset by default; use `--name "Base Name"` to
override it, or `--minimal-schema` to write only `_raw_log` instead of inferring
columns from the rule body. Review the inferred column types before uploading.

The same stdin contract applies to `summon correlation` (JSON in, correlation
rule YAML out).

---

## Validate

Validation checks your pack against demisto-sdk rules. Packs containing Python are also linted with ruff and have their unit tests run, both using the official demisto/content store setup, so lint and test failures surface before store submission rather than in the pipeline. Note this means validate executes your pack's test code:

```bash
python spellbook.py validate MyNewPack -c my-content/spellbook.yaml
```

To validate all packs at once:

```bash
python spellbook.py validate-all -c my-content/spellbook.yaml
```

---

## Build

Building creates a distributable zip file in the artefacts directory:

```bash
python spellbook.py build MyNewPack -c my-content/spellbook.yaml
```

To build all packs:

```bash
python spellbook.py build --all -c my-content/spellbook.yaml
```

If no packs are discovered, `build --all` and `validate-all` exit with a
grepable `[ERROR]` rather than reporting success. This is deliberate: in CI a
missing volume mount would otherwise produce a green pipeline and an empty
release. SamplePack is excluded from discovery, so an instance holding only
SamplePack counts as empty here; build it directly by name.

The zip files appear in my-content/artifacts/:

```
my-content/
+-- artifacts/
    +-- MyNewPack-v1.0.0.zip
    +-- SamplePack-v1.0.0.zip
```

---

## Upload

Upload your pack directly to Cortex Platform using the API.

First, set the required environment variables:

```bash
export DEMISTO_BASE_URL="https://your-cortex-instance.xdr.paloaltonetworks.com"
export DEMISTO_API_KEY="your-api-key"
export XSIAM_AUTH_ID="your-auth-id"
```

Then upload:

```bash
# Upload to Cortex Platform
python spellbook.py upload my-content/Packs/MyNewPack --platform

# Upload to XSOAR (no XSIAM_AUTH_ID or --platform flag needed)
python spellbook.py upload my-content/Packs/MyNewPack

# Upload with insecure connection (skip certificate validation)
# A grepable [WARN] Certificate validation: disabled (--insecure) line is
# emitted to stdout so CI logs make the condition explicit.
python spellbook.py upload my-content/Packs/MyNewPack --platform --insecure

# Legacy XSIAM upload (use only for tenants not yet on Cortex Platform;
# silently drops Jobs and other Platform-only content types)
python spellbook.py upload my-content/Packs/MyNewPack --xsiam
```

---

## Version Management

Spellbook provides commands for managing pack versions.

Show current version information:

```bash
python spellbook.py version MyNewPack -c my-content/spellbook.yaml
```

Set a specific version:

```bash
python spellbook.py set-version MyNewPack 2.0.0 -c my-content/spellbook.yaml

# Set version and create Git tag (stages all pack files)
python spellbook.py set-version MyNewPack 2.0.0 --tag -c my-content/spellbook.yaml
```

Bump version automatically:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
python spellbook.py bump-version MyNewPack -c my-content/spellbook.yaml

# Bump revision explicitly (1.0.0 -> 1.0.1)
python spellbook.py bump-version MyNewPack --revision -c my-content/spellbook.yaml

# Bump minor version (1.0.0 -> 1.1.0)
python spellbook.py bump-version MyNewPack --minor -c my-content/spellbook.yaml

# Bump major version (1.0.0 -> 2.0.0)
python spellbook.py bump-version MyNewPack --major -c my-content/spellbook.yaml

# Bump version and create a Git tag
python spellbook.py bump-version MyNewPack --tag -c my-content/spellbook.yaml

# Bump version with custom commit message (for CI/CD integration)
python spellbook.py bump-version MyNewPack --tag -m "Closes #123" -c my-content/spellbook.yaml
```

---

## Harmless Warnings

The following warnings can be safely ignored during normal operation:

[INFO] "Could not get repository properties: Remote named 'origin' didn't exist"

This message appears when working locally without a Git remote configured. It is expected behaviour for local-only development and does not affect building or validation.

[INFO] "AG100 validation in the pre-commit GitHub Action fails..."

This is informational text about GitHub Actions validation. It does not indicate an error with your local build process.

---

## Command Reference

All commands below assume you are in the gocortex-spellbook directory:

| Action | Command |
|--------|---------|
| List packs | python spellbook.py list-packs -c my-content/spellbook.yaml |
| Create pack | python spellbook.py create PackName -c my-content/spellbook.yaml |
| Create pack without author image | python spellbook.py create PackName --no-author-image -c my-content/spellbook.yaml |
| Validate pack | python spellbook.py validate PackName -c my-content/spellbook.yaml |
| Validate all | python spellbook.py validate-all -c my-content/spellbook.yaml |
| Build pack | python spellbook.py build PackName -c my-content/spellbook.yaml |
| Build all | python spellbook.py build --all -c my-content/spellbook.yaml |
| Build without validation | python spellbook.py build --all --no-validate -c my-content/spellbook.yaml |
| Show version | python spellbook.py version PackName -c my-content/spellbook.yaml |
| Set version | python spellbook.py set-version PackName X.Y.Z -c my-content/spellbook.yaml |
| Bump version | python spellbook.py bump-version PackName -c my-content/spellbook.yaml |
| Bump and tag | python spellbook.py bump-version PackName --tag -c my-content/spellbook.yaml |
| Bump with message | python spellbook.py bump-version PackName --tag -m "Closes #123" -c my-content/spellbook.yaml |
| Import correlations | cat rules.json \| python spellbook.py summon correlation PackName -c my-content/spellbook.yaml |
| Import data model rule | cat rule.xif \| python spellbook.py summon datamodel PackName -c my-content/spellbook.yaml |
| Generate from template | python spellbook.py summon template intel_retrohunt PackName --set KEY=VALUE -c my-content/spellbook.yaml |
| List templates | python spellbook.py summon template --list -c my-content/spellbook.yaml |
