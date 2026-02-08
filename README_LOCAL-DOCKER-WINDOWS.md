# GoCortex Spellbook - Windows Docker Workflow

This guide provides Windows-specific Docker commands for PowerShell and Command Prompt users. It mirrors the main [README_LOCAL-DOCKER.md](README_LOCAL-DOCKER.md) guide with syntax adapted for Windows environments.

---

## Syntax Reference

| Element | Linux/macOS | PowerShell | Command Prompt |
|---------|-------------|------------|----------------|
| Current directory | `$(pwd)` | `${PWD}` | `%cd%` |
| Home directory | `~` | `$env:USERPROFILE` | `%USERPROFILE%` |
| Line continuation | `\` | `` ` `` (backtick) | `^` |
| Set environment variable | `export VAR=val` | `$env:VAR="val"` | `set VAR=val` |

---

## Alternative: Git Bash

If you have Git for Windows installed, Git Bash provides a Unix-like shell where the standard Linux/macOS commands work without modification. This is often the simplest option for Windows users.

---

## Prerequisites

- Docker Desktop for Windows installed and running
- PowerShell or Command Prompt

---

## Get Spellbook

Pull the pre-built image from GitHub Container Registry:

```powershell
docker pull ghcr.io/gocortexio/spellbook:latest
```

This command works identically in PowerShell and Command Prompt.

---

## Create a Content Instance

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook init my-content --author "Your Organisation"
```

To skip GitHub Actions (Docker-only workflow), add `--no-ci` to the end of the command.

---

## Initialise Git

These commands work identically in PowerShell and Command Prompt:

```powershell
cd my-content
git init
git branch -M main
git add .
git commit -s -m "Initial commit"
```

---

## List Packs

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook list-packs
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook list-packs
```

---

## Create a New Pack

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook create MyNewPack --description "My new content pack"
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook create MyNewPack --description "My new content pack"
```

---

## Validate

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook validate MyNewPack
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook validate MyNewPack
```

To validate all packs, replace `validate MyNewPack` with `validate-all`.

---

## Build

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook build MyNewPack
```

To build all packs:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook build --all
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook build MyNewPack
```

To build all packs:

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook build --all
```

---

## Upload

First, set the required environment variables.

### PowerShell

```powershell
$env:DEMISTO_BASE_URL="https://your-cortex-instance.xdr.paloaltonetworks.com"
$env:DEMISTO_API_KEY="your-api-key"
$env:XSIAM_AUTH_ID="your-auth-id"
```

Then upload to XSIAM:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  -e DEMISTO_BASE_URL `
  -e DEMISTO_API_KEY `
  -e XSIAM_AUTH_ID `
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --xsiam
```

Upload to XSOAR (no XSIAM_AUTH_ID or --xsiam flag needed):

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  -e DEMISTO_BASE_URL `
  -e DEMISTO_API_KEY `
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack
```

### Command Prompt

```cmd
set DEMISTO_BASE_URL=https://your-cortex-instance.xdr.paloaltonetworks.com
set DEMISTO_API_KEY=your-api-key
set XSIAM_AUTH_ID=your-auth-id
```

Then upload to XSIAM:

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  -e DEMISTO_BASE_URL ^
  -e DEMISTO_API_KEY ^
  -e XSIAM_AUTH_ID ^
  ghcr.io/gocortexio/spellbook upload Packs/MyNewPack --xsiam
```

---

## Version Management

### PowerShell

Show current version:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook version MyNewPack
```

Set a specific version:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0
```

Set version and create Git tag (stages all pack files):

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0 --tag
```

Bump version (revision by default):

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook bump-version MyNewPack
```

Bump minor version:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --minor
```

Bump major version:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --major
```

Bump and create Git tag:

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

Bump with custom commit message (for CI/CD integration):

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag -m "Closes #123"
```

### Command Prompt

Show current version:

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook version MyNewPack
```

Set a specific version:

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0
```

Set version and create Git tag (stages all pack files):

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook set-version MyNewPack 2.0.0 --tag
```

Bump version (revision by default):

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook bump-version MyNewPack
```

Bump and create Git tag:

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag
```

Bump with custom commit message (for CI/CD integration):

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook bump-version MyNewPack --tag -m "Closes #123"
```

---

## Command Reference

The standard Docker invocation pattern for Windows:

### PowerShell

```powershell
docker run --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook <command>
```

### Command Prompt

```cmd
docker run --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
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
| Validate pack | validate PackName |
| Validate all | validate-all |
| Build pack | build PackName |
| Build all | build --all |
| Upload pack | upload PackName |
| Upload to XSIAM | upload PackName --xsiam |
| Show version | version PackName |
| Set version | set-version PackName X.Y.Z |
| Bump version | bump-version PackName |
| Bump revision | bump-version PackName --revision |
| Bump minor | bump-version PackName --minor |
| Bump major | bump-version PackName --major |
| Bump and tag | bump-version PackName --tag |
| Bump with message | bump-version PackName --tag -m "Closes #123" |
| Import correlations | summon correlation PackName (with stdin) |

---

## Summon (Import from Platform)

The summon command imports content exported from the Cortex Platform.

### Importing Correlation Rules

Export correlation rules from XSIAM as JSON, then pipe to the summon command.

#### PowerShell

```powershell
Get-Content exported_rules.json | docker run -i --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

For interactive paste (paste JSON then press Ctrl+D):

```powershell
docker run -it --rm `
  -v ${PWD}:/content `
  -v $env:USERPROFILE\.gitconfig:/home/spellbook/.gitconfig:ro `
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

#### Command Prompt

```cmd
type exported_rules.json | docker run -i --rm ^
  -v %cd%:/content ^
  -v %USERPROFILE%\.gitconfig:/home/spellbook/.gitconfig:ro ^
  ghcr.io/gocortexio/spellbook summon correlation MyPack
```

The command:
- Parses the JSON array of correlation rules
- Removes platform-specific fields (rule_id, simple_schedule, etc.)
- Adds required fields (global_rule_id, fromversion)
- Creates YAML files in Packs/MyPack/CorrelationRules/

---

## Troubleshooting

### Path Issues

If you encounter path-related errors, ensure:

- Docker Desktop is running
- You are in the correct directory (your content instance folder)
- The path does not contain spaces (or wrap the path in quotes if it does)

### Git Config Not Found

If the `.gitconfig` mount fails, check that your Git configuration file exists:

PowerShell:
```powershell
Test-Path $env:USERPROFILE\.gitconfig
```

Command Prompt:
```cmd
dir %USERPROFILE%\.gitconfig
```

If the file does not exist, configure Git first:

```cmd
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```
