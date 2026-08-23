# Orion — PDF Editor for Desktop
# Copyright (C) 2026 Marco Lombardo
#
# SPDX-License-Identifier: AGPL-3.0-or-later
# Distributed WITHOUT ANY WARRANTY; see LICENSE for the full terms.
# A commercial licence, without the AGPL's obligations, is available for use
# in proprietary or closed-source products — see COMMERCIAL-LICENSE.md.

"""Test package.

``__init__.py`` is here on purpose: several test modules import shared helpers
with ``from tests.conftest import ...``.  Without it that only works when
pytest happens to be started as ``python -m pytest`` (which puts the working
directory on ``sys.path``); a bare ``pytest`` — what CI runs — fails to collect.
"""
