"""Content checks for uploaded files (ARCHITECTURE.md section 1.2)."""
from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET

from PIL import Image

MAX_FILE_BYTES = 10 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def check_png(data: bytes) -> str | None:
    """Returns an error message, or None when the PNG is usable."""
    if not data.startswith(PNG_SIGNATURE):
        return "is not a PNG file"
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.convert("RGBA")
    except Exception:  # noqa: BLE001 - any decode failure is a bad upload
        return "could not be read as an RGBA image"
    return None


def _xml_root(data: bytes) -> str | None:
    try:
        return ET.fromstring(data).tag
    except ET.ParseError:
        return None


def _json_object(data: bytes) -> dict | None:
    try:
        value = json.loads(data)
    except (ValueError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def check_tileset(ext: str, data: bytes) -> str | None:
    if ext == ".tsx":
        return None if _xml_root(data) == "tileset" else "is not a TSX file (XML with root <tileset>)"
    if ext == ".tsj":
        return None if _json_object(data) is not None else "is not a TSJ file (JSON object)"
    return "must have extension .tsx or .tsj"


def check_map(ext: str, data: bytes) -> str | None:
    if ext == ".tmx":
        return None if _xml_root(data) == "map" else "is not a TMX file (XML with root <map>)"
    if ext == ".tmj":
        obj = _json_object(data)
        ok = obj is not None and isinstance(obj.get("layers"), list)
        return None if ok else "is not a TMJ file (JSON object with 'layers')"
    return "must have extension .tmx or .tmj"
