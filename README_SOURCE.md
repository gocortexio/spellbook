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
pip install -r requirements.txt
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

---

## Rename Content (If Copying From Other Packs)

If you have copied content items from another pack, the internal names will not match your pack name. This causes upload failures. Fix this by running:

```bash
python spellbook.py rename-content MyNewPack -c my-content/spellbook.yaml
```

This command updates all content item names and IDs to match your pack name.

---

## Validate

Validation checks your pack against demisto-sdk rules:

```bash
python spellbook.py validate MyNewPack -c my-content/spellbook.yaml
```

To validate all packs at once:

```bash
python spellbook.py validate-all -c my-content/spellbook.yaml
```

---

## Lint (Optional)

Linting runs additional code quality checks using demisto-sdk pre-commit hooks:

```bash
python spellbook.py lint MyNewPack -c my-content/spellbook.yaml
```

This step is optional but recommended before uploading to production systems.

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

The zip files appear in my-content/artifacts/:

```
my-content/
+-- artifacts/
    +-- MyNewPack-1.0.0.zip
    +-- SamplePack-1.0.0.zip
```

---

## Upload

Upload your pack directly to Cortex Platform using the API.

First, set the required environment variables:

```bash
export DEMISTO_BASE_URL="https://your-cortex-instance.com"
export DEMISTO_API_KEY="your-api-key"
export XSIAM_AUTH_ID="your-auth-id"
```

Then upload:

```bash
# Upload to Cortex Platform
python spellbook.py upload my-content/Packs/MyNewPack --zip --xsiam

# Upload a pre-built zip file
python spellbook.py upload my-content/artifacts/MyNewPack-1.0.0.zip

# Upload with insecure connection (skip certificate validation)
python spellbook.py upload my-content/artifacts/MyNewPack-1.0.0.zip --insecure
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
| Rename content | python spellbook.py rename-content PackName -c my-content/spellbook.yaml |
| Validate pack | python spellbook.py validate PackName -c my-content/spellbook.yaml |
| Validate all | python spellbook.py validate-all -c my-content/spellbook.yaml |
| Lint pack | python spellbook.py lint PackName -c my-content/spellbook.yaml |
| Build pack | python spellbook.py build PackName -c my-content/spellbook.yaml |
| Build all | python spellbook.py build --all -c my-content/spellbook.yaml |
| Show version | python spellbook.py version PackName -c my-content/spellbook.yaml |
| Set version | python spellbook.py set-version PackName X.Y.Z -c my-content/spellbook.yaml |
| Bump version | python spellbook.py bump-version PackName -c my-content/spellbook.yaml |
