# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: GoCortexIO
"""
XDM Field Knowledge Module

Records XDM fields that a data model rule may not assign. Each is a real
path in the published XDM schema, so every offline check that only asks "is
this a real field?" passes it, but it belongs to a data model other than the
event model a [MODEL] rule maps to. The tenant refuses the rule ("<field> is
not part of the selected data model"), and a pack carrying it fails to
install or installs without compiling. The fields may still be referenced
elsewhere (correlation rule XQL, investigation queries).

demisto-sdk has no registry of XDM field assignability, so this list is
maintained here from field-verified failures, in the same spirit as the
XSIAM validator rules, and kept in step with the cortex-platform-xdm-author
skill's banned-field registry. Every entry must be evidence-based; do not
add fields on suspicion.
"""

import re


# Fields unusable as data model rule mapping targets.
UNMAPPABLE_XDM_FIELDS = frozenset({
    # XCloud asset-inventory attribute (asset types such as t2.micro, gp3),
    # not part of any event data model. Failed on a tenant.
    "xdm.source.cloud.source_type",
    # The same asset attribute on the target and intermediate entities,
    # banned with it; not separately reproduced on a tenant.
    "xdm.target.cloud.source_type",
    "xdm.intermediate.cloud.source_type",
    # Listed upstream as a Boolean beside xdm.target.user.groups, but not in
    # the event model. Refused by the tenant's data model rule editor, and a
    # pack install carrying it sat an hour in Installing then failed with a
    # 101704 naming nothing (2026-10-27). The group's name belongs in
    # xdm.target.user.groups.
    "xdm.target.user.group",
})

_STRING_LITERAL_PATTERN = re.compile(r'"(?:[^"\\\n]|\\.)*"')
_COMMENT_PATTERN = re.compile(r"//.*")


def _clean_line(line: str) -> str:
    """Blank out string literals and comments so they cannot match.

    Literals are stripped before comments so a ``//`` inside a quoted
    string does not swallow the rest of the line.
    """
    line = _STRING_LITERAL_PATTERN.sub(" ", line)
    return _COMMENT_PATTERN.sub(" ", line)


def scan_unmappable_fields(
    text: str, extra_fields: set[str] | None = None
) -> list[dict]:
    """Scan XIF text for unmappable XDM fields, line by line.

    Returns a list of findings, each ``{"field", "line", "assignment"}``.
    ``assignment`` is True when the field is a mapping target (followed by
    a single ``=``, excluding ``==``, ``!=``, ``~=`` comparisons), which is
    the deterministically fatal case. Occurrences inside comments and
    string literals are ignored, and matching is boundary-safe so a longer
    field name that merely contains a listed one does not match.

    Args:
        text: Raw XIF rule text.
        extra_fields: Additional field names to scan for.

    Returns:
        Findings ordered by line number.
    """
    fields = set(UNMAPPABLE_XDM_FIELDS) | set(extra_fields or ())
    patterns = {
        field: re.compile(r"(?<![\w.])" + re.escape(field) + r"(?![\w.])")
        for field in fields
    }

    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        cleaned = _clean_line(line)
        for field, pattern in patterns.items():
            for match in pattern.finditer(cleaned):
                remainder = cleaned[match.end():]
                assignment = bool(re.match(r"\s*=(?![=~])", remainder))
                findings.append(
                    {"field": field, "line": line_number, "assignment": assignment}
                )
    return findings
