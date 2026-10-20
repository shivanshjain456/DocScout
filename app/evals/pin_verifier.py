"""Verification and drift detection for pinned instruction-bearing components (O8).

Enforces:
- External instruction-bearing files (configurations, prompts, models, tool definitions)
  are hashed and pinned in `config/security_pins.json`.
- Any modification after approval is detected as drift, failing the build gate.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


class DriftDetectedError(Exception):
    """Raised when an instruction-bearing component does not match its approved hash."""


def verify_security_pins(
    pin_path: str = "config/security_pins.json",
    override_pins: dict[str, str] | None = None,
) -> bool:
    """Verify that all pinned files match their approved sha256 digests.

    Raises:
        DriftDetectedError: If any pinned file has been modified, deleted, or corrupted.
    """
    if override_pins is not None:
        pins = override_pins
    else:
        path = Path(pin_path)
        if not path.exists():
            raise DriftDetectedError(f"Security pin file not found: {pin_path}")
        with open(path, encoding="utf-8") as f:
            pins = json.load(f)

    for file_str, expected_hash in pins.items():
        target = Path(file_str)
        if not target.exists():
            raise DriftDetectedError(f"Pinned file is missing: {file_str}")

        with open(target, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()

        if actual_hash != expected_hash:
            raise DriftDetectedError(
                f"Security drift detected in {file_str}!\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}"
            )

    return True
