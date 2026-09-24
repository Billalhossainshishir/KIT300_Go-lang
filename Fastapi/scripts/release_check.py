r"""Release package sanity checks for RAMIFY OS."""
from __future__ import annotations
import json, sys, zipfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PARTS = {".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
FORBIDDEN_SUFFIXES = {".pyc", ".pyo", ".bat", ".ps1", ".sh"}
PRIVATE_NAMES = {"signer_key.json", "private_key.json", "keys.json"}
REQUIRED_DOCS = {"01_Requirements_Specification.pdf", "02_Architecture.pdf", "03_Test_Report.pdf", "04_User_Guide.pdf", "05_Final_Presentation.pptx", "06_Demo_Script.pdf"}

def fail(message: str) -> None:
    print("FAIL:", message); raise SystemExit(1)

def private_path(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    lowered = "/".join(rel.parts).lower()
    if "seed_private" in lowered: return True
    if path.name.lower() in {"signer_key.json", "private_key.json"}: return True
    return False

def main() -> None:
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
    print(f"PASS: RAMIFY OS {version} package is version-consistent, cache-clean and contains no shipped private signer material.")

if __name__ == "__main__": main()
