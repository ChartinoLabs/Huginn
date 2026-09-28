"""Fixture job module that fails while it is being imported."""

import not_installed_pkg  # noqa: F401  # ty: ignore[unresolved-import]
