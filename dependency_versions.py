"""Report the locked runtime dependency versions used by DevOps MCP."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version


RUNTIME_PACKAGES = ("fastmcp", "uvicorn", "starlette")


def dependency_versions() -> dict[str, str]:
    """Return deterministic package/version metadata for health and CI."""
    versions: dict[str, str] = {}
    for package in RUNTIME_PACKAGES:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


if __name__ == "__main__":
    print(json.dumps(dependency_versions(), sort_keys=True))
