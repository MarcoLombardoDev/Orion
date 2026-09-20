# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Parsing XML that arrived inside somebody else's document.

An XFA packet is XML from an untrusted file, so the parser has to be hostile
to it. Three attacks matter and all three are refused here rather than
mitigated:

**XXE.** ``<!DOCTYPE x [<!ENTITY f SYSTEM "file:///etc/passwd">]>`` makes a
careless parser read a local file, or fetch a URL, and paste the result into
the document. **Billion laughs.** Nested entity definitions that expand to
gigabytes from a few hundred bytes. **Quadratic blowup.** One enormous entity
referenced repeatedly.

Every one of them needs a ``<!DOCTYPE`` declaration, and no legitimate XFA
packet has one: XFA is defined by a schema, entities are not part of how
LiveCycle writes forms, and nothing in the format needs a DTD. So the rule
here is simply that a DOCTYPE is a refusal. That is stronger than disabling
entity expansion — there is no cleverness left to get wrong — and it needs no
third-party library.

Two more limits guard the cases a DOCTYPE ban does not cover: a size cap,
because a genuinely enormous packet would exhaust memory before any of this
matters, and a depth cap, because deeply nested elements can exhaust the
stack. Both are generous next to any real form.

``xml.etree.ElementTree`` is the standard library's parser and, for the record
on why it is safe *here*: since Python 3.7 it does not expand external
entities, but it still **accepts** internal ones, which is the billion-laughs
case. Banning the DOCTYPE closes that.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from xml.parsers import expat

__all__ = ["MAX_XML_BYTES", "MAX_XML_DEPTH", "XmlRejected", "parse_xml", "local_name"]

log = logging.getLogger(__name__)

#: 64 MB. A large real form is a few hundred kilobytes; a packet past this is
#: not a form Orion is going to be able to do anything useful with anyway.
MAX_XML_BYTES = 64 * 1024 * 1024

#: XFA nests subforms, but not like this. Real templates sit well under 100.
MAX_XML_DEPTH = 256


class XmlRejected(ValueError):
    """The XML was refused before it was parsed, or while it was.

    Carries a message meant for a person, because this is one of the few
    failures the user will actually be shown.
    """


def _build(data: bytes) -> ElementTree.Element:
    """Drive expat by hand, with every dangerous handler refusing outright.

    ``ElementTree.XMLParser`` would be the obvious vehicle and is the wrong
    one: its C implementation keeps the expat parser private, so the DOCTYPE
    handler cannot be reached, and the ``doctype`` method it used to offer for
    exactly this is deprecated and ignored. Creating the expat parser here
    makes the refusals explicit and impossible to bypass silently.
    """
    builder = ElementTree.TreeBuilder()
    # "}" as the separator gives "uri}local", one character off ElementTree's
    # own "{uri}local", which the start handler completes.
    parser = expat.ParserCreate(namespace_separator="}")
    depth = 0

    def start(tag: str, attrs: dict) -> None:
        nonlocal depth
        depth += 1
        if depth > MAX_XML_DEPTH:
            raise XmlRejected(
                f"The form's XML nests more than {MAX_XML_DEPTH} levels deep, "
                "which no real form does."
            )
        builder.start("{" + tag if "}" in tag else tag, attrs)

    def end(tag: str) -> None:
        nonlocal depth
        depth -= 1
        builder.end("{" + tag if "}" in tag else tag)

    def reject_doctype(name, sysid, pubid, has_internal_subset):
        raise XmlRejected(
            "The form's XML declares a document type, which XFA never needs "
            "and which is how XML files attack the programs that read them. "
            "Orion will not parse it."
        )

    def reject_entity(*args, **kwargs):
        raise XmlRejected("The form's XML defines entities, which Orion will not expand.")

    def reject_external(*args, **kwargs):
        raise XmlRejected(
            "The form's XML refers to something outside the file. Orion does "
            "not fetch anything a document asks it to."
        )

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.EntityDeclHandler = reject_entity
    parser.UnparsedEntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_external
    # No expat default: an undefined entity must fail rather than vanish.
    parser.DefaultHandler = None

    parser.Parse(data, True)
    return builder.close()


def parse_xml(data: bytes | str) -> ElementTree.Element:
    """Parse *data* into an element tree, or raise :class:`XmlRejected`.

    Nothing is fetched, no entity is expanded, and no file the document names
    is ever opened.
    """
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    if not data:
        raise XmlRejected("The form's XML is empty.")
    if len(data) > MAX_XML_BYTES:
        raise XmlRejected(
            f"The form's XML is larger than {MAX_XML_BYTES // (1024 * 1024)} MB."
        )

    try:
        return _build(data)
    except XmlRejected:
        raise
    except expat.ExpatError as exc:
        raise XmlRejected(f"The form's XML is not well formed: {exc}") from exc
    except RecursionError as exc:  # pragma: no cover - the depth cap fires first
        raise XmlRejected("The form's XML nests too deeply to parse.") from exc


def local_name(tag: str) -> str:
    """``{http://…/xfa-template/3.0/}subform`` -> ``subform``.

    XFA packets are namespaced, and the namespace URI carries a version that
    changes between LiveCycle releases. Matching on the local name is what
    makes the parser work across all of them.
    """
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag
