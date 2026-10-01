# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
GoCortex Spellbook - Cortex Platform Content Pack Builder

A Python-based toolset for building, validating, and packaging
Cortex Platform content packs.
"""

__version__ = "1.25.4"
__author__ = "GoCortexIO - Simon Sigre"

# The single fromversion every generated entity declares.
#
# A pack used to come out split: collectors at 6.10.0, modelling and parsing
# rules at 8.3.0, correlation rules at 8.4.0. The platform takes the highest, so
# the other values were not lower floors but silent no-ops, and a reader
# comparing two files in one pack could not tell which one governed.
#
# 8.4.0 is a HOUSE decision, not a store requirement - upstream content ships
# plenty at 6.8.0, which is the commonest value there. It is set here so the
# choice is made once and visibly, rather than four times by accident.
HOUSE_FROM_VERSION = "8.4.0"

# Set by the Dockerfile from the VCS_REF build argument. Empty in a plain
# `docker build` and when running from a source checkout.
REVISION_ENV_VAR = "SPELLBOOK_REVISION"

UNSTAMPED_BUILD = "local build, unstamped"


def build_version() -> str:
    """Return a version string that identifies the BUILD, not just the release.

    `--version` used to report ``__version__`` alone, which cannot tell two
    builds apart: every image built from any tree reports whatever that literal
    last said. Three images spanning a week all answered "1.23.0", and the
    published image of that name is not even built from this tree. A downstream
    session confirming what it was about to release read the right number off
    the wrong binary, and there was no second symptom to catch it.

    The image label cannot fix this on its own. Labels are daemon-side image
    metadata, readable with `docker image inspect` but NOT by the running
    container, so the revision has to be promoted to an environment variable at
    build time to reach this process.

    An unset revision is meaningful rather than missing: it is what a plain
    `docker build` or a source checkout produces, so it is named as such
    instead of being passed off as a release.
    """
    import os

    revision = os.environ.get(REVISION_ENV_VAR, "").strip()
    if revision:
        return f"{__version__} ({revision[:8]})"
    return f"{__version__} ({UNSTAMPED_BUILD})"
