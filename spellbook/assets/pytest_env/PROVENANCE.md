# Vendored pytest scaffolding

These files are copied byte-identical from the demisto/content repository so
that `spellbook validate` can run a pack's unit tests the way the official
content pipeline does. demisto-sdk does not ship them: the pipeline stages
them from a content checkout, which a Spellbook instance does not have.

Source: https://github.com/demisto/content
Commit: c07760e45e714ed17643790350216b43d4238b9c
Copied: 2026-07-24

| File | Source path in demisto/content |
|------|--------------------------------|
| demistomock.py | Tests/demistomock/demistomock.py |
| CommonServerPython.py | Packs/Base/Scripts/CommonServerPython/CommonServerPython.py |
| DemistoClassApiModule.py | Packs/ApiModules/Scripts/DemistoClassApiModule/DemistoClassApiModule.py |
| conftest.py | Tests/scripts/dev_envs/pytest/conftest.py |

The files are unmodified. `LICENSE` is the demisto/content MIT licence, which
covers them all; it is included so the attribution travels with the code.
Do not edit these files. Any local change would silently diverge Spellbook's
results from the pipeline they exist to mirror.

## Why DemistoClassApiModule.py matters

`CommonServerPython.py` ends with an unconditional
`from DemistoClassApiModule import *`. Without this file, every
`from CommonServerPython import *` raises
`ModuleNotFoundError: No module named 'DemistoClassApiModule'`, which is every
integration test in every pack. It was missed in the original vendoring and
found in the field. When refreshing, check whether CommonServerPython has
gained any further content-repo imports:

```bash
grep -nE "^\s*(from|import) [A-Z]" spellbook/assets/pytest_env/CommonServerPython.py
```

Anything that returns must be vendored here and added to `SCAFFOLDING` in
`spellbook/pack_tests.py`.

## Why conftest.py matters

It supplies two autouse fixtures that fail a test which writes to stdout or
stderr, or which logs at WARNING or above. That is what catches an integration
calling `demisto.error(...)` on a path a test exercises, since demistomock's
`error()` prints. The fix for such a failure belongs in the test (patch
`demisto.error`), not in the production logging.

## Refresh procedure

Refresh alongside each demisto-sdk pin bump. A drifting CommonServerPython.py
is the main way local results diverge from the official pipeline, in either
direction.

```bash
SHA=$(gh api repos/demisto/content/commits/master --jq .sha)
for p in "Tests/demistomock/demistomock.py:demistomock.py" \
         "Packs/Base/Scripts/CommonServerPython/CommonServerPython.py:CommonServerPython.py" \
         "Packs/ApiModules/Scripts/DemistoClassApiModule/DemistoClassApiModule.py:DemistoClassApiModule.py" \
         "Tests/scripts/dev_envs/pytest/conftest.py:conftest.py"; do
  gh api "repos/demisto/content/contents/${p%%:*}?ref=$SHA" --jq .content \
    | base64 -d > "spellbook/assets/pytest_env/${p##*:}"
done
gh api "repos/demisto/content/contents/LICENSE?ref=$SHA" --jq .content \
  | base64 -d > spellbook/assets/pytest_env/LICENSE
```

Verify each file still matches upstream, then update the commit and date above:

```bash
git hash-object spellbook/assets/pytest_env/demistomock.py
gh api "repos/demisto/content/contents/Tests/demistomock/demistomock.py?ref=$SHA" --jq .sha
```
