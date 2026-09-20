# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""XFA forms: recognising them, reading them, and turning them into PDFs.

XFA is a form format Adobe layered *on top of* PDF. The PDF is a shell; the
form lives in an XML package hanging off the AcroForm dictionary, and the
pages of a **dynamic** XFA carry nothing but a "please wait" notice, because
the real page content is supposed to be laid out at open time by a viewer that
understands XFA. Almost nothing does any more — Adobe deprecated it, Chrome and
Firefox never implemented it, and pdfium, which is what Orion renders with, is
built without it. That is why these documents open blank everywhere and why no
ordinary editor will touch them.

What this package does about it, honestly stated:

* **Reads** the XFA package out of the PDF and parses the XML safely, into a
  model that owes nothing to any PDF library.
* **Lays the template out itself**, because for a dynamic form there is no
  page content to preserve — the appearance has to be *computed* from the
  template, not copied from the file.
* **Writes a new, ordinary PDF** with a drawn visual layer and real AcroForm
  fields, which every reader and the rest of Orion can edit.

What it does not do, and will not pretend to: run XFA scripts, reproduce
dynamic pagination, or grow repeatable sections on demand. Those have no
AcroForm equivalent. The conversion keeps what is there and the report says
plainly what was left behind — see :class:`~orion.xfa.report.XfaConversionReport`
and its two separate fidelity figures.

The original file is never modified. Every conversion writes a new document.

Layering: this package is framework-neutral, like ``orion.pdf``. Nothing here
imports Qt.
"""

from __future__ import annotations

from orion.xfa.analyzer import XfaScriptAnalysis, analyse_scripts, summarise_form
from orion.xfa.converter import ConversionResult, convert_xfa, convert_xfa_file
from orion.xfa.detector import FormInfo, PdfFormType, detect_form_type, inspect_form
from orion.xfa.engine import XfaEngine, choose_engine, pdfium_supports_xfa
from orion.xfa.model import (
    XfaButton,
    XfaChoiceList,
    XfaDocument,
    XfaField,
    XfaFieldType,
    XfaScript,
    XfaSubform,
    XfaTemplate,
)
from orion.xfa.parser import parse_xfa
from orion.xfa.report import ConversionMode, Fidelity, XfaConversionReport
from orion.xfa.validator import ValidationResult, validate_converted_pdf

__all__ = [
    "ConversionMode",
    "ConversionResult",
    "Fidelity",
    "FormInfo",
    "PdfFormType",
    "ValidationResult",
    "XfaButton",
    "XfaChoiceList",
    "XfaConversionReport",
    "XfaDocument",
    "XfaEngine",
    "XfaField",
    "XfaFieldType",
    "XfaScript",
    "XfaScriptAnalysis",
    "XfaSubform",
    "XfaTemplate",
    "analyse_scripts",
    "choose_engine",
    "convert_xfa",
    "convert_xfa_file",
    "detect_form_type",
    "inspect_form",
    "parse_xfa",
    "pdfium_supports_xfa",
    "summarise_form",
    "validate_converted_pdf",
]
