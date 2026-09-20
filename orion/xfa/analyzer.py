# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Reading the form's scripts without running any of them.

Nothing in this module executes anything. There is no interpreter, no ``eval``,
no sandbox to escape from, because no code path here ever treats the script
text as anything but a string to look at. That is the whole security posture
for XFA scripts and it is deliberately the simplest one available: a form from
an untrusted source gets read, not obeyed.

What the analysis is *for* is the report. "Three scripts were not converted"
tells a user nothing they can act on. "The total is no longer worked out for
you, and the Add a row button no longer adds rows" tells them exactly what
they have lost and whether they can live with it.

Why none of it converts is not a limitation of effort. XFA scripts address a
live form object model — ``xfa.form``, SOM expressions, instance managers,
``xfa.layout`` — and an AcroForm has none of those objects. A translated
script would compile and then refer to nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orion.xfa.model import XfaDocument, XfaScript, XfaScriptKind

__all__ = ["XfaScriptAnalysis", "analyse_scripts", "describe_kind", "summarise_form"]


#: What each kind of script did, said so a non-programmer can weigh the loss.
_CONSEQUENCES = {
    XfaScriptKind.VALIDATION: "checked what you typed before letting you continue",
    XfaScriptKind.CALCULATION: "worked out a value from the other fields for you",
    XfaScriptKind.INITIALIZATION: "set the form up when it opened",
    XfaScriptKind.EVENT_HANDLER: "reacted as you moved through the form",
    XfaScriptKind.BUTTON_ACTION: "did something when a button was pressed",
    XfaScriptKind.DYNAMIC_LAYOUT: "added or removed parts of the form as you went",
    XfaScriptKind.VISIBILITY: "showed or hid parts of the form",
    XfaScriptKind.ENABLE_DISABLE: "locked or unlocked fields as you went",
    XfaScriptKind.VALUE_ASSIGNMENT: "filled a field in from somewhere else",
    XfaScriptKind.UNKNOWN: "did something the form's designer wrote by hand",
}


def describe_kind(kind: XfaScriptKind) -> str:
    return _CONSEQUENCES.get(kind, _CONSEQUENCES[XfaScriptKind.UNKNOWN])


@dataclass(frozen=True, slots=True)
class XfaScriptAnalysis:
    """One script, classified. The source is carried, never executed."""

    kind: XfaScriptKind
    owner: str
    event: str
    source: str
    language: str
    convertible: bool
    reason: str

    @property
    def consequence(self) -> str:
        return describe_kind(self.kind)

    @classmethod
    def of(cls, script: XfaScript) -> XfaScriptAnalysis:
        return cls(
            kind=script.kind,
            owner=script.owner,
            event=script.event,
            source=script.source,
            language=script.language,
            convertible=script.convertible,
            reason=script.reason,
        )


@dataclass(slots=True)
class FormSummary:
    """A quick read of what a form contains, for the dialog that offers to convert."""

    fields: int = 0
    interactive: int = 0
    buttons: int = 0
    choice_lists: int = 0
    date_fields: int = 0
    repeatable: int = 0
    instances: int = 0
    scripts: int = 0
    pages: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


def analyse_scripts(document: XfaDocument) -> list[XfaScriptAnalysis]:
    """Classify every script in *document*. Nothing is run."""
    return [XfaScriptAnalysis.of(script) for script in document.scripts]


def summarise_form(document: XfaDocument) -> FormSummary:
    """Count what is in the form, for telling the user before they commit."""
    from orion.xfa.model import XfaFieldType

    summary = FormSummary(pages=document.template.page_count)
    for item in document.fields:
        summary.fields += 1
        summary.by_type[item.field_type.value] = summary.by_type.get(item.field_type.value, 0) + 1
        if item.is_interactive:
            summary.interactive += 1
        if item.field_type is XfaFieldType.CHOICE:
            summary.choice_lists += 1
        elif item.field_type is XfaFieldType.DATE:
            summary.date_fields += 1

    summary.buttons = len(document.buttons)
    summary.scripts = len(document.scripts)
    repeatable = document.repeatable_subforms
    summary.repeatable = len(repeatable)
    summary.instances = sum(max(s.occur.initial, s.occur.min, 1) for s in repeatable)
    return summary
