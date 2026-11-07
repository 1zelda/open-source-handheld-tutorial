from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

from . import db


class PackageError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_arcname(name: str) -> str:
    cleaned = name.replace("\\", "/").strip()
    pure = PurePosixPath(cleaned)
    if not cleaned or pure.is_absolute() or ".." in pure.parts or ":" in pure.parts[0]:
        raise PackageError(f"unsafe archive path: {name!r}")
    if cleaned.endswith("/"):
        raise PackageError(f"directory entries are not supported: {name!r}")
    return str(pure)


def build_package(output: Path, files: list[dict], job_id: str, recipe_id: str) -> dict:
    if not files:
        raise PackageError("package has no files")
    output.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    seen = set()
    for item in files:
        if "src" not in item:
            raise PackageError("package entry missing src")
        src = Path(item["src"])
        if not src.is_file():
            raise PackageError(f"package source missing: {src}")
        arcname = safe_arcname(item.get("arcname") or src.name)
        if arcname in seen:
            raise PackageError(f"duplicate archive entry: {arcname}")
        seen.add(arcname)
        entries.append({
            "arcname": arcname,
            "size": src.stat().st_size,
            "sha256": _sha256(src),
            "src": src,
        })

    manifest = {
        "format_version": 1,
        "created_at": db.now(),
        "job_id": job_id,
        "recipe_id": recipe_id,
        "files": [{k: e[k] for k in ("arcname", "size", "sha256")} for e in entries],
    }
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            zf.write(entry["src"], entry["arcname"])
        zf.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    size = output.stat().st_size
    return {
        "path": str(output),
        "size": size,
        "sha256": _sha256(output),
        "manifest": manifest,
    }


def verify_package(path: Path) -> dict:
    if not path.is_file():
        raise PackageError(f"package missing: {path}")
    with zipfile.ZipFile(path, "r") as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            raise PackageError("duplicate entries in package")
        for name in names:
            if safe_arcname(name) != name:
                raise PackageError(f"unsafe entry: {name!r}")
        if "MANIFEST.json" not in names:
            raise PackageError("MANIFEST.json missing")
        try:
            manifest = json.loads(zf.read("MANIFEST.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PackageError(f"invalid MANIFEST.json: {exc}") from exc
        if manifest.get("format_version") != 1:
            raise PackageError("unsupported manifest format")
        listed = {entry["arcname"]: entry for entry in manifest.get("files", [])}
        actual = set(names) - {"MANIFEST.json"}
        if set(listed) != actual:
            raise PackageError(f"manifest mismatch: listed={sorted(listed)} actual={sorted(actual)}")
        evidence = []
        for name, entry in listed.items():
            data = zf.read(name)
            digest = hashlib.sha256(data).hexdigest()
            if len(data) != entry.get("size"):
                raise PackageError(f"size mismatch: {name}")
            if digest != entry.get("sha256"):
                raise PackageError(f"sha256 mismatch: {name}")
            evidence.append({"arcname": name, "size": len(data), "sha256": digest})
    return {
        "file_count": len(evidence),
        "files": evidence,
        "package_size": path.stat().st_size,
        "package_sha256": _sha256(path),
    }
