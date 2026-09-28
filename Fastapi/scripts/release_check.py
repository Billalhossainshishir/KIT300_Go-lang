r"""Release package sanity checks for RAMIFY OS."""
from __future__ import annotations
import json, re, sys, zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".bat", ".ps1", ".sh"}
PRIVATE_NAMES = {"signer_key.json", "private_key.json", "keys.json"}
REQUIRED_DOCS = {"01_Requirements_Specification.pdf", "02_Architecture.pdf", "03_Test_Report.pdf", "04_User_Guide.pdf", "05_Final_Presentation.pptx", "06_Demo_Script.pdf"}
SECRET_NAMES = {"signer_key.json", "keys.json", "id_rsa", ".env"}
SECRET_DIRS = {"seed_private"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SCANNED_SUFFIXES = {".json", ".txt", ".md", ".py", ".js", ".yaml", ".yml", ".cfg", ".ini", ""}
PEM_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
NAMED_PRIVATE_HEX = re.compile(r'"[^"]*private[^"]*"\s*:\s*"([0-9a-fA-F]{32,})"', re.IGNORECASE)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")

def fail(message: str) -> None:
    print("FAIL:", message); raise SystemExit(1)

def _known_public_keys() -> set[str]:
    source = (ROOT / "backend" / "ramify" / "crypto" / "embedded_pubkeys.py").read_text(encoding="utf-8")
    return set(HEX64.findall(source))


def _derives_to(value: str, publics: set[str]) -> bool:
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
        if any(part in SECRET_DIRS for part in rel.parts):
            found.append(f"{rel} (private key directory)")
            continue
        if any(part in FORBIDDEN_PARTS for part in rel.parts):
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
        if any(_derives_to(value, publics) for value in set(HEX64.findall(text))):
            found.append(f"{rel} (secret for a shipped public key)")
    if found:
        fail("private signing material in the release: " + "; ".join(sorted(found)))


def private_path(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    lowered = "/".join(rel.parts).lower()
    if "seed_private" in lowered: return True
    if path.name.lower() in {"signer_key.json", "private_key.json"}: return True
    return False

def main() -> None:
    check_no_private_keys()
    version=(ROOT/"VERSION.txt").read_text().strip(); pyproject=(ROOT/"pyproject.toml").read_text(); guide=(ROOT/"HOW_TO_RUN.txt").read_text()
    if f'version = "{version}"' not in pyproject: fail("pyproject.toml version does not match VERSION.txt")
    if version not in guide: fail("HOW_TO_RUN.txt does not mention current version")
    docs={p.name for p in (ROOT/"docs").glob("*") if p.is_file()}; missing=sorted(REQUIRED_DOCS-docs)
    if missing: fail("missing formal docs: "+", ".join(missing))
    bad=[]; private=[]
    for path in ROOT.rglob("*"):
        rel=path.relative_to(ROOT)
        if any(part in FORBIDDEN_PARTS for part in rel.parts) or path.suffix.lower() in FORBIDDEN_SUFFIXES: bad.append(str(rel))
        if path.is_file() and private_path(path): private.append(str(rel))
    if bad: fail("forbidden release files found: "+", ".join(bad[:10]))
    if private: fail("private signing material must not ship: "+", ".join(private))
    pack=ROOT/"RAMIFY-Extended-Proof-Pack.zip"
    if not pack.is_file(): fail("Extended Proof Pack is missing")
    with zipfile.ZipFile(pack) as z:
        names=z.namelist()
        if "manifest.json" not in names: fail("Extended Proof Pack has no manifest.json")
        for name in names:
            low=name.lower()
            if "seed_private" in low or low.endswith("signer_key.json") or low.endswith("private_key.json"):
                fail("Extended Proof Pack contains private signing material: "+name)
        try: manifest=json.loads(z.read("manifest.json"))
        except Exception as exc: fail(f"Extended Proof Pack manifest is invalid: {type(exc).__name__}")
        if manifest.get("app_version") != version: fail("Extended Proof Pack app_version does not match VERSION.txt")
        if manifest.get("verifier_version") != "portable-verify-v2": fail("Extended Proof Pack verifier version is not v2")
        if not manifest.get("manifest_signature"): fail("Extended Proof Pack manifest is not signed")
    print(f"PASS: RAMIFY OS {version} package is version-consistent, cache-clean and contains no shipped private signer material.")

if __name__ == "__main__": main()
