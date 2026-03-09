"""
Firmware OTA update API endpoints.
Devices check for updates and download firmware binaries.
Web portal uploads and manages firmware versions.
"""

import hashlib
import os
import logging
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse, FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

FIRMWARE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "firmware")


def _version_tuple(v: str):
    """Parse '1.2.3' into (1, 2, 3) for comparison."""
    try:
        return tuple(int(x) for x in v.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


@router.get("/check")
async def firmware_check(
    request: Request,
    device_id: str = Query(...),
    variant: str = Query(...),
    current_version: str = Query(...),
):
    """Device calls this to check if a firmware update is available."""
    db = request.app.state.db

    active = db.get_active_firmware(variant)
    if not active:
        return JSONResponse({"update_available": False})

    if _version_tuple(active["version"]) <= _version_tuple(current_version):
        return JSONResponse({"update_available": False})

    logger.info(f"OTA update available for {device_id}: {current_version} -> {active['version']}")
    return JSONResponse({
        "update_available": True,
        "version": active["version"],
        "file_size": active["file_size"],
        "file_hash": active["file_hash"],
        "download_url": f"/api/firmware/download?id={active['id']}",
    })


@router.get("/download")
async def firmware_download(
    request: Request,
    id: int = Query(None),
    variant: str = Query(None),
):
    """Device downloads the firmware binary."""
    db = request.app.state.db

    if id:
        fw = db.get_firmware_by_id(id)
    elif variant:
        fw = db.get_active_firmware(variant)
    else:
        return JSONResponse({"error": "Provide id or variant"}, status_code=400)

    if not fw:
        return JSONResponse({"error": "Firmware not found"}, status_code=404)

    filepath = os.path.join(FIRMWARE_DIR, fw["filename"])
    if not os.path.exists(filepath):
        return JSONResponse({"error": "Firmware file missing"}, status_code=404)

    logger.info(f"OTA download: {fw['variant']} v{fw['version']} ({fw['file_size']} bytes)")
    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        headers={"Content-Length": str(fw["file_size"])},
    )
