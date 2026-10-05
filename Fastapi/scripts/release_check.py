r"""Release package sanity checks for RAMIFY OS.

Version consistency, the six formal documents, no build rubbish, and no
private signing material.

Run from the project root after unpacking a release ZIP:
  .\.venv\Scripts\python.exe scripts\release_check.py

Exits 1 on the first failure, so it can gate a release step. A self-check of
the private-key detection lives in backend/tests/test_release_check.py.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".bat", ".ps1", ".sh"}
REQUIRED_DOCS = {
    "01_Requirements_Specification.pdf",
    "02_Architecture.pdf",
    "03_Test_Report.pdf",
    "04_User_Guide.pdf",
    "05_Final_Presentation.pptx",
    "06_Demo_Script.pdf",
}

# Private signing material. Client review of 30 August 2026: the runtime signer
# key reached a shipped build, and anyone holding it can mint a receipt the
# verifier accepts, which inverts what the tamper-evidence demonstration
# proves. These checks fail the release rather than warning about it.
SECRET_NAMES = {"signer_key.json", "keys.json", "id_rsa", ".env"}
SECRET_DIRS = {"seed_private"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SCANNED_SUFFIXES = {".json", ".txt", ".md", ".py", ".js", ".yaml", ".yml", ".cfg", ".ini", ""}
PEM_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
# A hex value sitting under a field whose name says it is private.
NAMED_PRIVATE_HEX = re.compile(r'"[^"]*private[^"]*"\s*:\s*"([0-9a-fA-F]{32,})"', re.IGNORECASE)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def _known_public_keys() -> set[str]:
    """Public keys the build ships, read as text so this script imports nothing
    from the package it is checking."""
    source = (ROOT / "backend" / "ramify" / "crypto" / "embedded_pubkeys.py").read_text(
        encoding="utf-8"
    )
    return set(HEX64.findall(source))


def _derives_to(value: str, publics: set[str]) -> bool:
    """True when `value` is the Ed25519 secret behind one of `publics`.

    This is what catches a key file that has simply been renamed. Names and
    field labels can be changed; the arithmetic cannot.
    """
    try:
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(value))
    except ValueError:
        return False
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return public in publics


def check_no_private_keys() -> None:
    publics = _known_public_keys()
    found: list[str] = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in FORBIDDEN_PARTS or part in SECRET_DIRS for part in rel.parts):
            if any(part in SECRET_DIRS for part in rel.parts):
                found.append(f"{rel} (private key directory)")
            continue
        if path.name in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES:
            found.append(f"{rel} (name reserved for private key material)")
            continue
        if path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if PEM_PRIVATE.search(text):
            found.append(f"{rel} (PEM private key block)")
            continue
        if NAMED_PRIVATE_HEX.search(text):
            found.append(f"{rel} (hex value in a field named private)")
            continue
        leaked = [v for v in set(HEX64.findall(text)) if _derives_to(v, publics)]
        if leaked:
            found.append(f"{rel} (secret for a shipped public key)")

    if found:
        fail(
            "private signing material in the release: "
            + "; ".join(sorted(found))
            + ". Remove it, or run `python scripts/seed.py --rekey` and re-sign "
            "the fixtures, before shipping."
        )


def main() -> None:
    # First, and before anything cosmetic. In a working tree the forbidden-file
    # scan trips on .venv and friends, which would mask this one.
    check_no_private_keys()

    version = (ROOT / "VERSION.txt").read_text(encoding="utf-8").strip()
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    how_to_run = (ROOT / "HOW_TO_RUN.txt").read_text(encoding="utf-8")
    if f'version = "{version}"' not in pyproject:
        fail("pyproject.toml version does not match VERSION.txt")
    if version not in how_to_run:
        fail("HOW_TO_RUN.txt does not mention the current VERSION.txt value")

    docs = {p.name for p in (ROOT / "docs").glob("*") if p.is_file()}
    missing = sorted(REQUIRED_DOCS - docs)
    if missing:
        fail("missing formal docs: " + ", ".join(missing))

    bad = []
    for path in ROOT.rglob("*"):
        rel = path.relative_to(ROOT)
        if any(part in FORBIDDEN_PARTS for part in rel.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            bad.append(str(rel))
    if bad:
        fail("forbidden release files found: " + ", ".join(bad[:10]))

    print(
        f"PASS: RAMIFY OS {version} release package is clean, version-consistent "
        "and carries no private signing material."
    )


if __name__ == "__main__":
    main()
