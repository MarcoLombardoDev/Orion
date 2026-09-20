# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Which engine converts a form, and what to do when none can.

There is no library, anywhere, that renders XFA faithfully and is usable here.
That is the finding this file exists to record, arrived at by checking rather
than assuming:

* **pdfium**, which Orion renders with, *has* XFA entry points —
  ``FPDF_LoadXFA``, ``FPDF_GetXFAPacketCount``. They are compiled out of every
  published build, because XFA support is behind ``PDF_ENABLE_XFA`` and the
  wheels are not built with it. On the build Orion ships, ``FPDF_LoadXFA``
  returns 0 and the packet count is 0 whatever the document contains. The
  symbols exist; the feature does not.
* **pypdf** reads the XFA package — ``PdfReader.xfa`` — and nothing more. It
  does not lay out or render a form, and does not claim to.
* **reportlab** writes real AcroForm fields, which is what makes the native
  conversion possible at all, but knows nothing of XFA.

So the engine that does the work is Orion's own: parse the template, compute
the layout, draw it, and create the fields. It is the only approach available
and it is also the right one for a dynamic form, whose pages hold nothing
worth preserving.

The indirection here is for the day that changes. If a pdfium build with XFA
becomes available, or somebody writes a real renderer, a new engine slots in
by declaring that it can handle a document and doing so; nothing else in the
package needs to know.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from orion.xfa.detector import FormInfo, PdfFormType, inspect_form
from orion.xfa.report import ConversionMode

__all__ = [
    "FallbackRenderer",
    "NativeXfaEngine",
    "UnsupportedEngine",
    "XfaEngine",
    "choose_engine",
    "pdfium_supports_xfa",
]

log = logging.getLogger(__name__)


def pdfium_supports_xfa() -> bool:
    """Whether the pdfium in this build can actually load an XFA form.

    Asked of the library rather than assumed, because the answer depends on
    how the wheel was compiled and could change under us. A build without
    ``PDF_ENABLE_XFA`` still exports the symbols, so the test has to be a call
    and not a ``hasattr``.
    """
    try:
        import pypdfium2.raw as raw

        return bool(getattr(raw, "FPDF_LoadXFA", None)) and _probe_xfa(raw)
    except Exception:  # pragma: no cover - a pdfium this broken fails elsewhere
        log.debug("Could not determine pdfium's XFA support", exc_info=True)
        return False


def _probe_xfa(raw) -> bool:
    """Try ``FPDF_LoadXFA`` on a throwaway document and see if it means it."""
    import io

    import pypdfium2 as pdfium
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(10, 10, " ")
    pdf.save()
    buffer.seek(0)

    document = pdfium.PdfDocument(buffer)
    try:
        # A build with XFA compiled in returns a form type of its own for an
        # XFA document and, crucially, does not stub this out to 0 always.
        return bool(raw.FPDF_LoadXFA(document.raw))
    except Exception:  # pragma: no cover - a stub that raises is still a no
        return False
    finally:
        document.close()


class XfaEngine(ABC):
    """Something that can turn an XFA document into a standard PDF."""

    name = "engine"

    @abstractmethod
    def can_handle(self, info: FormInfo) -> bool:
        """Whether this engine is able to convert *info*'s document."""

    @abstractmethod
    def convert(
        self,
        source: Path,
        output: Path,
        *,
        mode: ConversionMode,
        info: FormInfo,
    ):
        """Convert, returning a :class:`~orion.xfa.converter.ConversionResult`."""

    def describe(self) -> str:
        return self.name


class NativeXfaEngine(XfaEngine):
    """Orion's own: parse the template, lay it out, draw it, add the fields.

    Handles every XFA document it is given, because for a dynamic form there
    is no alternative that preserves anything, and for a static one it still
    produces a form whose fields work.
    """

    name = "Orion's XFA converter"

    def can_handle(self, info: FormInfo) -> bool:
        return info.is_xfa and bool(info.packets)

    def convert(self, source: Path, output: Path, *, mode: ConversionMode, info: FormInfo):
        from orion.xfa.converter import convert_xfa

        return convert_xfa(source, output, mode=mode, info=info)


class FallbackRenderer(XfaEngine):
    """Keep the pages the document already has, and drop the form.

    For a **static** XFA this is a real answer: the pages carry the form's
    appearance, so copying them preserves it exactly, and only the fields are
    lost. For a dynamic one it preserves a placeholder, which is why the
    native engine is tried first and this is reached only when that fails.
    """

    name = "page copier"

    def can_handle(self, info: FormInfo) -> bool:
        return info.page_count > 0

    def convert(self, source: Path, output: Path, *, mode: ConversionMode, info: FormInfo):
        from pypdf import PdfReader, PdfWriter

        from orion.xfa.converter import ConversionResult
        from orion.xfa.report import XfaConversionReport

        report = XfaConversionReport(
            source_file=str(source),
            mode=ConversionMode.STATIC,
            detected_type=info.form_type.value,
        )
        try:
            reader = PdfReader(str(source))
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            # The XFA package goes; what is left has to be an ordinary PDF or
            # readers will keep treating it as a form they cannot show.
            root = writer._root_object
            if "/AcroForm" in root:
                del root["/AcroForm"]
            if "/NeedsRendering" in root:
                del root["/NeedsRendering"]
            with open(output, "wb") as handle:
                writer.write(handle)
        except Exception as exc:
            report.error(f"The document could not be copied: {exc}")
            return ConversionResult(None, report)

        report.output_file = str(output)
        report.pages = info.page_count
        report.static_elements = info.page_count
        if info.form_type is PdfFormType.XFA_DYNAMIC:
            report.warn(
                "The form's design could not be read, so the converted document "
                "shows only what the original pages held — which for this kind "
                "of form is a placeholder rather than the form itself."
            )
        else:
            report.info(
                "The pages were kept exactly as they were; the fields are no "
                "longer fillable."
            )
        return ConversionResult(output, report)


class UnsupportedEngine(XfaEngine):
    """The honest refusal, for a document nothing here can do anything with."""

    name = "unsupported"

    def can_handle(self, info: FormInfo) -> bool:
        return True

    def convert(self, source: Path, output: Path, *, mode: ConversionMode, info: FormInfo):
        from orion.xfa.converter import ConversionResult
        from orion.xfa.report import XfaConversionReport

        report = XfaConversionReport(
            source_file=str(source),
            mode=mode,
            detected_type=info.form_type.value,
        )
        report.error(
            "This document's form cannot be converted: its design could not be "
            "read and its pages could not be copied."
        )
        return ConversionResult(None, report)


#: Tried in order. The first that says it can handle the document gets it.
ENGINES: tuple[XfaEngine, ...] = (NativeXfaEngine(), FallbackRenderer(), UnsupportedEngine())


def choose_engine(info: FormInfo, mode: ConversionMode = ConversionMode.KEEP_FIELDS) -> XfaEngine:
    """The engine for this document and this mode.

    A request for a static conversion of a *static* XFA goes straight to the
    page copier: its pages already are the form's appearance, so copying them
    is more faithful than redrawing them from the template.
    """
    if mode is ConversionMode.STATIC and info.form_type is PdfFormType.XFA_STATIC:
        return ENGINES[1]
    for engine in ENGINES:
        if engine.can_handle(info):
            return engine
    return ENGINES[-1]  # pragma: no cover - UnsupportedEngine always handles


def convert(
    source: str | Path,
    output: str | Path,
    *,
    mode: ConversionMode = ConversionMode.KEEP_FIELDS,
):
    """Convert *source* with whichever engine suits it, falling back if needed.

    The fallback is what makes a partial result the normal outcome rather than
    an error: if the native engine cannot read the template, the pages are
    still copied and the user still gets a document.
    """
    source_path = Path(source)
    output_path = Path(output)
    info = inspect_form(source_path)

    engine = choose_engine(info, mode)
    result = engine.convert(source_path, output_path, mode=mode, info=info)
    if result.succeeded:
        return result

    if not isinstance(engine, FallbackRenderer):
        log.info("%s could not convert %s; copying the pages instead", engine.name, source_path)
        fallback = FallbackRenderer()
        if fallback.can_handle(info):
            second = fallback.convert(source_path, output_path, mode=mode, info=info)
            for entry in result.report.entries:
                second.report.entries.append(entry)
            return second
    return result
