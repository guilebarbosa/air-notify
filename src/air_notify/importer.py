"""
Read AirTag keys from an export, in memory, so they can go straight into the secret store.

Supported inputs:
- the zip from OpenTagViewer's exporter (`--no-password`): OwnedBeacons/<uuid>.plist plus
  KeyAlignmentRecords/<uuid>/<record>.plist, and BeaconNamingRecord/ for the name
- a single beacon .plist (optionally with --alignment <plist>)
- FindMy.py accessory JSON
"""

from __future__ import annotations

import json
import plistlib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from findmy import FindMyAccessory


class ExportFormatError(ValueError):
    """The export can't be read."""


def load_accessories(path: Path, alignment: Path | None = None) -> dict[str, FindMyAccessory]:
    """Return accessories keyed by beacon id (the file stem for single files)."""
    if zipfile.is_zipfile(path):
        return _from_zip(path)
    if path.suffix == ".json":
        return {path.stem: FindMyAccessory.from_json(json.loads(path.read_text()))}
    return {path.stem: FindMyAccessory.from_plist(path, alignment)}


def _from_zip(path: Path) -> dict[str, FindMyAccessory]:
    with zipfile.ZipFile(path) as zf:
        try:
            plists = {PurePosixPath(n): plistlib.loads(zf.read(n)) for n in zf.namelist() if n.endswith(".plist")}
        except (RuntimeError, NotImplementedError) as e:
            msg = "The zip is password-protected. Re-export with --no-password (it goes straight into secret storage)."
            raise ExportFormatError(msg) from e

    beacons = {p.stem: data for p, data in plists.items() if p.parent.name == "OwnedBeacons"}
    if not beacons:
        msg = "No OwnedBeacons/*.plist in the zip"
        raise ExportFormatError(msg)

    result = {}
    for beacon_id, device in beacons.items():
        alignments = [
            data
            for p, data in plists.items()
            if p.parent.name == beacon_id and p.parent.parent.name == "KeyAlignmentRecords"
        ]
        # The most advanced alignment record gives the best starting point for key rotation.
        alignment = max(alignments, key=lambda a: a.get("lastIndexObserved", -1), default=None)
        result[beacon_id] = FindMyAccessory.from_plist(device, alignment, name=_name(plists, beacon_id))
    return result


def _name(plists: dict[PurePosixPath, dict[str, Any]], beacon_id: str) -> str | None:
    for p, data in plists.items():
        if "BeaconNamingRecord" not in p.parts:
            continue
        if beacon_id in p.parts or str(data.get("associatedBeacon", "")) == beacon_id:
            name = data.get("name")
            if isinstance(name, str) and name:
                return name
    return None
