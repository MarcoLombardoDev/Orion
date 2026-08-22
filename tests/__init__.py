"""Test package.

``__init__.py`` is here on purpose: several test modules import shared helpers
with ``from tests.conftest import ...``.  Without it that only works when
pytest happens to be started as ``python -m pytest`` (which puts the working
directory on ``sys.path``); a bare ``pytest`` — what CI runs — fails to collect.
"""
