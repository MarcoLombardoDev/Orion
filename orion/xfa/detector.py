# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""What kind of form, if any, a PDF actually carries.

Read from the document's own structure — the AcroForm dictionary, its ``/XFA``
entry, ``/NeedsRendering`` and the names of the packets inside the XFA package.
Never from the text on the page. A dynamic XFA renders as the words "If this
message is not eventually replaced…", and matching on that string would be
guessing at a symptom: the notice is only a convention, it is localised, some
producers word it differently, and a perfectly ordinary PDF is free to contain
the same sentence.

The distinction that matters most here is static versus dynamic, because it
decides whether the pages of the file are worth anything:

* **Static XFA** (XFA foreground) keeps a real, rendered page underneath the
  form. The appearance can be preserved by keeping that content.
* **Dynamic XFA** does not. The page is a placeholder, and the appearance has
  to be rebuilt from the template or it is lost.

Getting that wrong in the optimistic direction produces a converted file that
is blank, so where the evidence is ambiguous this leans towards dynamic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

__all__ = [
    "FormInfo",
    "PdfFormType",
    "XFA_PACKET_NAMES",
    "detect_form_type",
    "inspect_form",
]

log = logging.getLogger(__name__)

#: The packets an XFA package is built from. Only a few matter to us:
#: ``template`` is the form's design, ``datasets`` the data filled into it.
XFA_PACKET_NAMES = (
    "xdp",
    "template",
    "datasets",
    "config",
    "localeSet",
    "form",
    "sourceSet",
    "connectionSet",
    "xmpmeta",
    "pdf",
)


class PdfFormType(str, Enum):
    """What a PDF turned out to hold."""

    #: No form of any kind.
    NONE = "none"
    #: An ordinary interactive PDF form. Orion and every reader can edit this.
    ACROFORM = "acroform"
    #: XFA whose pages still carry their real content ("XFA foreground").
    XFA_STATIC = "xfa_static"
    #: XFA whose pages are a placeholder; the layout lives only in the template.
    XFA_DYNAMIC = "xfa_dynamic"
    #: XFA alongside a usable AcroForm field tree — the best case to convert.
    XFA_WITH_ACROFORM = "xfa_with_acroform"
    #: Fields were flattened into page content, or nothing recognisable is left.
    FLATTENED_OR_UNKNOWN = "flattened_or_unknown"

    @property
    def is_xfa(self) -> bool:
        return self in (
            PdfFormType.XFA_STATIC,
            PdfFormType.XFA_DYNAMIC,
            PdfFormType.XFA_WITH_ACROFORM,
        )

    @property
    def needs_conversion(self) -> bool:
        """True when Orion cannot edit the document as it stands.

        An XFA form is unusable in Orion — and in most readers — until it has
        been converted, which is the whole reason this package exists.
        """
        return self.is_xfa


@dataclass(frozen=True, slots=True)
class FormInfo:
    """Everything the detector learned, so nothing has to open the file twice."""

    form_type: PdfFormType
    #: Packet name -> XML bytes. Empty for a non-XFA document.
    packets: dict[str, bytes] = field(default_factory=dict)
    #: AcroForm field names, when there is an AcroForm field tree.
    acroform_fields: tuple[str, ...] = ()
    #: ``/NeedsRendering``: the producer's own statement that this is dynamic.
    needs_rendering: bool = False
    page_count: int = 0
    #: Why the detector decided what it decided, for the log and the report.
    reason: str = ""

    @property
    def template(self) -> bytes | None:
        return self.packets.get("template")

    @property
    def datasets(self) -> bytes | None:
        return self.packets.get("datasets")

    @property
    def is_xfa(self) -> bool:
        return self.form_type.is_xfa


def _packets_from_xfa(xfa_entry) -> dict[str, bytes]:
    """Pull the named packets out of an ``/XFA`` entry.

    ``/XFA`` is either one stream holding a whole XDP, or a flat array
    alternating name and stream: ``[(template) 4 0 R (datasets) 5 0 R …]``.
    Both shapes are common and a converter that handles only the array misses
    a good proportion of real files.
    """
    from pypdf.generic import ArrayObject, IndirectObject

    packets: dict[str, bytes] = {}
    entry = xfa_entry.get_object() if isinstance(xfa_entry, IndirectObject) else xfa_entry

    if isinstance(entry, ArrayObject):
        items = list(entry)
        for index in range(0, len(items) - 1, 2):
            try:
                name = str(items[index])
                stream = items[index + 1]
                data = stream.get_object().get_data()
            except Exception:  # pragma: no cover - a damaged packet, not fatal
                log.warning("Could not read XFA packet %r", items[index], exc_info=True)
                continue
            if isinstance(data, bytes) and data:
                packets[name] = data
        return packets

    # A single stream: the whole XDP in one piece.
    try:
        data = entry.get_data()
    except Exception:  # pragma: no cover - defensive
        log.warning("Could not read the XFA stream", exc_info=True)
        return packets
    if isinstance(data, bytes) and data:
        packets["xdp"] = data
    return packets


def _looks_dynamic(packets: dict[str, bytes], needs_rendering: bool) -> tuple[bool, str]:
    """Is this a dynamic form? And on what evidence.

    ``/NeedsRendering`` is the producer saying so outright and settles it.
    Failing that, the config packet usually carries the LiveCycle setting that
    decides it, and the template's own ``layout`` attributes give it away: a
    dynamic form flows its content, a static one positions it.
    """
    if needs_rendering:
        return True, "the document sets /NeedsRendering"

    config = packets.get("config", b"") + packets.get("xdp", b"")
    lowered = config.lower()
    # How LiveCycle records "dynamic" when it saves an interactive form.
    if b"<dynamicrender>required</dynamicrender>" in lowered.replace(b" ", b""):
        return True, "the XFA config asks for dynamic rendering"
    if b"dynamicrender" in lowered and b"required" in lowered:
        return True, "the XFA config asks for dynamic rendering"

    template = packets.get("template", b"") + packets.get("xdp", b"")
    lowered_template = template.lower()
    # A flowed subform grows and shrinks; that cannot be a positioned page.
    if b'layout="tb"' in lowered_template or b"layout='tb'" in lowered_template:
        return True, "the template flows its content rather than positioning it"
    if b"instancemanager" in lowered_template or b"occur" in lowered_template:
        return True, "the template declares repeatable sections"

    return False, "the template positions its content and nothing asks for rendering"


def inspect_form(source: str | Path | bytes) -> FormInfo:
    """Work out what form *source* carries, reading its structure.

    Accepts a path or the file's bytes, so callers that already hold the
    document in memory do not have to write it out first.

    Never raises for an unreadable file: a document this cannot open is one
    Orion will refuse elsewhere with a better message, and a detector that
    throws would turn "no form" into a crash on the open path.
    """
    import io

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError as PyPdfReadError

    try:
        handle = io.BytesIO(source) if isinstance(source, bytes) else str(source)
        reader = PdfReader(handle)
        page_count = len(reader.pages)
    except (PyPdfReadError, OSError, ValueError, KeyError) as exc:
        log.debug("Could not inspect %r for forms: %s", source, exc)
        return FormInfo(PdfFormType.FLATTENED_OR_UNKNOWN, reason="the file could not be read")
    except Exception:  # pragma: no cover - unexpected parser failure
        log.warning("Unexpected failure inspecting %r for forms", source, exc_info=True)
        return FormInfo(PdfFormType.FLATTENED_OR_UNKNOWN, reason="the file could not be read")

    try:
        root = reader.trailer["/Root"].get_object()
    except Exception:  # pragma: no cover - defensive
        return FormInfo(
            PdfFormType.FLATTENED_OR_UNKNOWN,
            page_count=page_count,
            reason="the document has no catalogue",
        )

    acroform = root.get("/AcroForm")
    acroform = acroform.get_object() if acroform is not None else None
    needs_rendering = bool(root.get("/NeedsRendering", False))

    if acroform is None:
        return FormInfo(
            PdfFormType.NONE,
            page_count=page_count,
            needs_rendering=needs_rendering,
            reason="the document has no AcroForm dictionary",
        )

    packets: dict[str, bytes] = {}
    if "/XFA" in acroform:
        packets = _packets_from_xfa(acroform["/XFA"])

    field_names: tuple[str, ...] = ()
    try:
        fields = reader.get_fields() or {}
        field_names = tuple(str(name) for name in fields)
    except Exception:  # pragma: no cover - a broken field tree is not fatal
        log.debug("Could not read the AcroForm field tree", exc_info=True)

    if not packets:
        if field_names:
            return FormInfo(
                PdfFormType.ACROFORM,
                acroform_fields=field_names,
                page_count=page_count,
                needs_rendering=needs_rendering,
                reason=f"an AcroForm with {len(field_names)} field(s) and no XFA",
            )
        return FormInfo(
            PdfFormType.FLATTENED_OR_UNKNOWN,
            page_count=page_count,
            needs_rendering=needs_rendering,
            reason="an AcroForm dictionary with neither fields nor XFA",
        )

    dynamic, why = _looks_dynamic(packets, needs_rendering)
    if field_names and not dynamic:
        # Both worlds, and the AcroForm side is usable: the easiest case there
        # is, because the field tree already says where everything belongs.
        return FormInfo(
            PdfFormType.XFA_WITH_ACROFORM,
            packets=packets,
            acroform_fields=field_names,
            page_count=page_count,
            needs_rendering=needs_rendering,
            reason=f"XFA alongside {len(field_names)} AcroForm field(s)",
        )

    form_type = PdfFormType.XFA_DYNAMIC if dynamic else PdfFormType.XFA_STATIC
    return FormInfo(
        form_type,
        packets=packets,
        acroform_fields=field_names,
        page_count=page_count,
        needs_rendering=needs_rendering,
        reason=why,
    )


def detect_form_type(source: str | Path | bytes) -> PdfFormType:
    """Just the verdict, for callers that want nothing else."""
    return inspect_form(source).form_type
