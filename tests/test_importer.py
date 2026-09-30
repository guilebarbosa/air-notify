from __future__ import annotations

import os
import plistlib
import zipfile
from datetime import datetime, UTC

import pytest

from air_notify.importer import ExportFormatError, load_accessories

PAIRED = datetime(2025, 1, 1, 12, 0)


def beacon_plist() -> dict:
    return {
        "privateKey": {"key": {"data": os.urandom(4) + os.urandom(28)}},
        "sharedSecret": {"key": {"data": os.urandom(32)}},
        "secondarySharedSecret": {"key": {"data": os.urandom(32)}},
        "pairingDate": PAIRED,
        "model": "AirTag1,1",
        "identifier": "BEACON-1",
    }


def write_zip(path, beacons: dict[str, dict], alignments: dict[str, list[dict]], names: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for uuid, data in beacons.items():
            zf.writestr(f"OwnedBeacons/{uuid}.plist", plistlib.dumps(data))
        for uuid, records in alignments.items():
            for i, record in enumerate(records):
                zf.writestr(f"KeyAlignmentRecords/{uuid}/rec{i}.plist", plistlib.dumps(record))
        for uuid, name in names.items():
            zf.writestr(f"BeaconNamingRecord/{uuid}/n.plist", plistlib.dumps({"associatedBeacon": uuid, "name": name}))


def test_zip_import_uses_latest_alignment_and_name(tmp_path):
    beacon = beacon_plist()
    path = tmp_path / "tags.zip"
    write_zip(
        path,
        {"B1": beacon},
        {
            "B1": [
                {"lastIndexObserved": 10, "lastIndexObservationDate": datetime(2026, 1, 1)},
                {"lastIndexObserved": 99, "lastIndexObservationDate": datetime(2026, 9, 1)},
            ]
        },
        {"B1": "Son's backpack"},
    )

    (acc,) = load_accessories(path).values()
    data = acc.to_json()
    assert data["master_key"] == beacon["privateKey"]["key"]["data"][-28:].hex()
    assert data["alignment_index"] == 99
    assert data["alignment_date"].startswith("2026-09-01")
    assert data["name"] == "Son's backpack"
    assert data["paired_at"] == PAIRED.replace(tzinfo=UTC).isoformat()


def test_zip_without_beacons_is_rejected(tmp_path):
    path = tmp_path / "empty.zip"
    write_zip(path, {}, {}, {})
    with pytest.raises(ExportFormatError):
        load_accessories(path)


def test_json_round_trip(tmp_path):
    zpath = tmp_path / "tags.zip"
    write_zip(zpath, {"B1": beacon_plist()}, {}, {})
    (acc,) = load_accessories(zpath).values()

    jpath = tmp_path / "airtag.json"
    jpath.write_text(__import__("json").dumps(acc.to_json()))
    (again,) = load_accessories(jpath).values()
    assert again.to_json() == acc.to_json()
