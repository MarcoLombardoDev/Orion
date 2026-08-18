"""Allow ``python -m orion``."""

from orion.main import main

if __name__ == "__main__":  # pragma: no cover - thin wrapper
    raise SystemExit(main())
