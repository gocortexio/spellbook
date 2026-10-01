# GoCortex Spellbook - Local Docker Workflow

GoCortex Spellbook is a toolset for building, validating, and packaging Cortex Platform content packs. It solves the problem of creating compliant content packs without needing to understand the intricacies of the demisto-sdk and Cortex Platform schema requirements.

This guide walks you through building Cortex Platform content packs using Docker on your local machine.

---

## Prerequisites

- Docker installed and running

---

## Get Spellbook

Pull the pre-built image from GitHub Container Registry (preferred):

```bash
docker pull ghcr.io/gocortexio/spellbook:latest
```

`:latest` does not say which build you got. `spellbook --version` reports the
commit an image was built from, so it can confirm what you are actually
running: an image published by CI prints `1.25.4 (<commit>)`, while one built
locally with `docker build` prints `1.25.4 (local build, unstamped)`. Images
published before 1.24.0 predate the build stamp and report a bare version with
no identifier, so match the image ID to tell those apart. The stamp cannot
distinguish two local builds from each other: every local build is unstamped.

All commands in this guide use the registry image. If you prefer to build locally:

```bash
git clone <spellbook-repo-url>
cd gocortex-spellbook
docker build -t ghcr.io/gocortexio/spellbook .
```

---

## Create a Content Instance

Run this command from the directory where you want your content instance created:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

This creates a my-content folder containing:

- Packs directory with a SamplePack to get you started
- spellbook.yaml configuration file
- GitHub Actions workflows (optional)

To skip GitHub Actions (Docker-only workflow):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation" --no-ci
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

---

## Explore SamplePack

Your instance includes a SamplePack with example content. List the available packs:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook list-packs
```

The SamplePack contains starter templates for common content types including integrations, scripts, playbooks, and Cortex Platform content like modelling rules and parsing rules.

---

## Create a New Pack

[WARNING] Always use the create command to make new packs. Never copy existing packs directly, as this causes naming conflicts during upload.

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook create MyNewPack --description "My new content pack"
```

This creates a properly structured pack with all required metadata files.

Options:

- `--author "Name"` sets the pack author. Without it, the author from `spellbook.yaml` `defaults.author` is used.
- `--template default|integration|playbook|minimal` selects which content directories are scaffolded.
- `--no-author-image` skips the placeholder author image.

By default `create` scaffolds a placeholder `Author_image.png` (the GoCortexIO
wordmark) at the pack root. Replace it with your own branding, or pass
`--no-author-image` to skip it:

```bash
docker run --rm -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook create MyNewPack \
  --author "My Organisation" --no-author-image
```

---

## Validate

Validation checks your pack against demisto-sdk rules. Packs containing Python are also linted with ruff and have their unit tests run, both using the official demisto/content store setup, so lint and test failures surface before store submission rather than in the pipeline. Note this means validate executes your pack's test code:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook validate MyNewPack
```

To validate all packs at once:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook validate-all
```

---

## Pack Attribution

Every pack must carry `CONTRIBUTORS.json` at its root. `validate` fails
without it, so `create` always writes one and a new pack passes from the start.

It is seeded with a fixed Spellbook maintainer entry, `["Simon Sigre
(packs@gocortex.io)"]`, NOT with `--author`, which names the publishing
organisation and belongs in `pack_metadata.json`. Replace it with your own
before publishing.

The format is demisto-sdk's: a flat JSON array of names.

```json
[
    "Simon Sigre"
]
```

If you have packs created before this became a requirement, add one line each:

```bash
echo '["Your Name"]' > Packs/MyPack/CONTRIBUTORS.json
```

If `create` reports `[WARN] no author configured`, it wrote no file. Pass
`--author "Your Name"`, or set `defaults.author` in `spellbook.yaml`.

---

## Format Python

When `validate` reports that Python content is not formatted as the pipeline
expects, run:

```bash
docker run --rm \
  -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook format MyNewPack
```

Do NOT run plain `ruff format` instead. It uses ruff's default line length of
88 where the pipeline uses 130, so it splits lines `validate` had already
accepted and the pack ends up further from passing. `spellbook format` uses
the same configuration `validate` checks against.

This is the only command that edits files in your pack. It runs only when you
type it, and it applies the formatter alone -- lint findings are left for you,
since fixing those is a judgement call.

---

## Build

Building creates a distributable zip file in the artefacts directory:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook build MyNewPack
```

To build all packs:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook build --all
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

## Check the Environment

`check-init` reports what spellbook can see: versions, config, and whether the
upload credentials are present.

Pass the same `-e` variables you would pass to `upload`. They are read from
inside the container, so without them `check-init` reports them as not set even
when they are exported on your host - the one command whose job is diagnosis
gives a confidently wrong answer:

```bash
docker run --rm \
  -v $(pwd):/content \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook check-init
```

The bare `-e NAME` form passes the value through from your shell, so no secret
is written into the command or your shell history.

Missing credentials are reported as `[INFO]`, not a failure - the command still
confirms the instance is ready for local builds.

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
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --platform

# Upload to XSOAR (no XSIAM_AUTH_ID or --platform flag needed)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack

# Upload with insecure connection (skip certificate validation)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --platform --insecure
```

### Existing packs

If you have packs created with an earlier Spellbook version, their `pack_metadata.json` `marketplaces` array may not include `"platform"`. Open each pack's `pack_metadata.json` and ensure the array reads:

```json
"marketplaces": [
  "xsoar",
  "marketplacev2",
  "platform"
]
```

Without `"platform"` in this array, demisto-sdk will skip every content item in the pack during a `--platform` upload.

### Legacy XSIAM upload

The older `--xsiam` flag is still accepted for tenants that have not yet migrated to the unified Cortex Platform. It maps to demisto-sdk's `--marketplace marketplacev2` and silently drops Jobs and any other content type whose parser does not list `MarketplaceV2` as supported. Prefer `--platform` whenever possible:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  -e DEMISTO_BASE_URL \
  -e DEMISTO_API_KEY \
  -e XSIAM_AUTH_ID \
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --xsiam
```

---

## Version Management

Spellbook provides commands for managing pack versions.

Show current version information:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook version MyNewPack
```

Set a specific version:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0

# Set version and create Git tag (stages all pack files)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0 --tag
```

Bump version automatically:

```bash
# Bump revision (1.0.0 -> 1.0.1) - default behaviour
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack

# Bump revision explicitly (1.0.0 -> 1.0.1)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --revision

# Bump minor version (1.0.0 -> 1.1.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --minor

# Bump major version (1.0.0 -> 2.0.0)
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --major

# Bump version and create a Git tag
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

---

## Git Configuration for Tagging

When using the `--tag` flag with `bump-version` or `set-version`, the container needs access to your Git identity to create commits and tags. The `--tag` flag stages all files in the pack directory, commits them, and creates a Git tag. Mount your local git config file:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

Use the `--message` or `-m` flag to specify a custom commit message for CI/CD integration (e.g., auto-closing issues):

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag -m "Closes #123"
```

The `:ro` suffix mounts the file as read-only for security. Without this mount, you will see the error "Author identity unknown".

---

## Harmless Warnings

The following warnings can be safely ignored during normal operation:

[INFO] "Could not get repository properties: Remote named 'origin' didn't exist"

This message appears when working locally without a Git remote configured. It is expected behaviour for local-only development and does not affect building or validation.

[INFO] "AG100 validation in the pre-commit GitHub Action fails..."

This is informational text about GitHub Actions validation. It does not indicate an error with your local build process.

---

## Summon (Import from Platform)

The summon command imports content exported from the Cortex Platform.

### Importing Correlation Rules

Export correlation rules from XSIAM as JSON, then pipe to the summon command:

```bash
cat exported_rules.json | docker run -i --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

For interactive paste (paste JSON, then press Ctrl+D - or Ctrl+Z then Enter on Windows):

```bash
docker run -it --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

The command:
- Parses the JSON array of correlation rules
- Removes platform-specific fields (rule_id, simple_schedule, etc.)
- Adds required fields (global_rule_id, fromversion)
- Creates YAML files in Packs/MyPack/CorrelationRules/

### Importing a Data Model Rule

Copy a data model (XDM) rule from the tenant rule editor, including its
`[MODEL: dataset="..."]` header, then pipe the XIF to the summon command:

```bash
cat rule.xif | docker run -i --rm \
  -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook summon datamodel MyPack
```

For interactive paste (paste the XIF, then press Ctrl+D - or Ctrl+Z then Enter on Windows):

```bash
docker run -it --rm -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook summon datamodel MyPack
```

The command writes the three-file modelling rule package (`.yml`, `.xif`,
`_schema.json`) with matching filenames into `Packs/MyPack/ModelingRules/`. The
package is named after the dataset by default (for example
`cloudflare_account_audit_raw` becomes `CloudflareAccountAudit`), so a pack can
hold many rules. Options:

- `--name "Base Name"` overrides the derived name; the `ModelingRule` suffix is appended automatically.
- `--minimal-schema` writes only `_raw_log` to the schema instead of inferring columns from the rule body.

Schema columns are inferred from the fields the rule reads, so `_raw_log` is
declared only when the rule reads it. Review the inferred types before uploading:
most are written as `string`, and the `[WARN]` output names the columns whose
type most likely needs correcting.

### Import a Parsing Rule

Copy the rule text from the tenant editor, including its `[INGEST: ...]`
header, and pipe it in:

```bash
cat rule.xif | docker run --rm -i \
  -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook summon parsing MyNewPack
```

For interactive paste (paste the XIF, then press Ctrl+D - or Ctrl+Z then Enter
on Windows):

```bash
docker run -it --rm -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook summon parsing MyNewPack
```

`-i` is what connects your terminal to the container. Without it Docker gives
the container an empty stdin, so the command reads end-of-file immediately and
exits before you can paste anything.

This writes the two-file parsing rule package (`.yml` and `.xif`) with
matching stems into `ParsingRules/`, named after the target dataset. Use
`--name` to override the name.

Use the importer rather than creating the pair by hand. demisto-sdk finds the
`.xif` from the `.yml` stem, so a directory holding only a `.xif` registers no
content item at all: the pack validates, uploads and installs, and the rule
never runs.

---


## Uplifting an Existing Repo

A pack created before a value was set in `spellbook.yaml` keeps the empty value
it was scaffolded with, and nothing carried a later change down to it.
`sync-defaults` fills them in: `url`, `email`, `githubUser` and
`CONTRIBUTORS.json`.

```bash
# report what would change, write nothing
docker run --rm -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook sync-defaults --all

# make the changes
docker run --rm -v $(pwd):/content \
  ghcr.io/gocortexio/spellbook sync-defaults --all --apply
```

Only EMPTY fields are filled. A pack holding a different value keeps it and the
difference is reported, so a deliberate per-pack choice is never discarded.
Nothing is written without `--apply`.

`categories` is not synced. It is a per-pack decision, and `validate` already
errors on an empty one rather than guessing a value.

For findings that are not identity values - a missing `isFetchEvents`, a
description without a full stop - `demisto-sdk validate --fix` handles a fair
share. It rewrites the whole YAML rather than patching it, so check the diff on
any file carrying comments.

---

## Command Reference

All commands below assume you are in the my-content directory. The standard Docker invocation is:

```bash
docker run --rm \
  -v $(pwd):/content \
  -v ~/.gitconfig:/home/spellbook/.gitconfig:ro \
  ghcr.io/gocortexio/spellbook <command>
```

Replace `<command>` with any of the following:

| Action | Command |
|--------|---------|
| Initialise instance | init my-content --author "Your Name" |
| Check environment | check-init |
| List instances | list-instances |
| List packs | list-packs |
| Create pack | create PackName |
| Create pack without author image | create PackName --no-author-image |
| Validate pack | validate PackName |
| Validate all | validate-all |
| Format pack Python | format PackName |
| Build pack | build PackName |
| Build all | build --all |
| Build without validation | build --all --no-validate |
| Upload pack | upload PackName (or upload Packs/PackName) |
| Upload to Cortex Platform | upload Packs/PackName --platform |
| Upload to XSIAM (legacy) | upload Packs/PackName --xsiam |
| Upload without validation | upload Packs/PackName --platform --skip-validation |
| Show version | version PackName |
| Set version | set-version PackName X.Y.Z |
| Bump version | bump-version PackName |
| Bump revision | bump-version PackName --revision |
| Bump minor | bump-version PackName --minor |
| Bump major | bump-version PackName --major |
| Bump and tag | bump-version PackName --tag |
| Bump with message | bump-version PackName --tag -m "Closes #123" |
| Preview identity sync | sync-defaults --all |
| Apply identity sync | sync-defaults --all --apply |
| Rename content | rename-content PackName (temporarily disabled - refuses and prints manual steps) |
| Import correlations | summon correlation PackName (with stdin) |
| Import data model rule | summon datamodel PackName (with stdin) |
| Import parsing rule | summon parsing PackName (with stdin) |
| Generate from template | summon template intel_retrohunt PackName --set KEY=VALUE |
| List templates | summon template --list |
