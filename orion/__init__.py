# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Orion — PDF Editor for Desktop.

A modular, fully offline PDF viewer, editor, annotator and page organiser.
"""

APP_NAME = "Orion"
APP_SUBTITLE = "PDF Editor for Desktop"
APP_ID = "orion"
ORGANISATION = "Orion"
__version__ = "1.7.0"

APP_AUTHOR = "Marco Lombardo"
APP_COPYRIGHT_YEAR = "2026"

#: Where commercial licensing enquiries go. Single source of truth: the
#: interface, the README and COMMERCIAL-LICENSE.md must never disagree.
CONTACT_EMAIL = "marco.lombardo@gmail.com"

#: Shown along the bottom of the window, and deliberately not something the
#: interface can be built without.
#:
#: AGPL-3.0 section 5 requires the work to carry Appropriate Legal Notices,
#: and section 7(b) lets an author require that attribution be preserved.
#: Iris, Proteus and Argus have all shown this line since their first
#: release; Orion shipped v1.0.0 without it, which was an oversight rather
#: than a decision.
#:
#: Not translated, because it is a legal notice rather than interface copy.
LICENSE_NOTICE = (
    f"© {APP_COPYRIGHT_YEAR} {APP_AUTHOR} — {APP_NAME}"
    "  |  Licensed under AGPL-3.0"
    "  |  Commercial licensing:"
)

#: Subject line pre-filled when the address in the notice is clicked.
LICENSING_SUBJECT = f"{APP_NAME} — commercial licence enquiry"

__all__ = [
    "APP_NAME",
    "APP_SUBTITLE",
    "APP_ID",
    "APP_AUTHOR",
    "APP_COPYRIGHT_YEAR",
    "ORGANISATION",
    "CONTACT_EMAIL",
    "LICENSE_NOTICE",
    "LICENSING_SUBJECT",
    "__version__",
]
