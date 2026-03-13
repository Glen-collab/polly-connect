"""
Device management endpoints
"""

from datetime import datetime
from typing import Dict
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()
devices: Dict[str, dict] = {}


class DeviceRegister(BaseModel):
    device_id: str


class DeviceProvision(BaseModel):
    claim_code: str


@router.post("/register")
async def register_device(device: DeviceRegister):
    devices[device.device_id] = {
        "device_id": device.device_id,
        "registered_at": datetime.utcnow().isoformat(),
        "status": "online"
    }
    return {"message": "Registered", "device_id": device.device_id}


@router.post("/provision")
async def provision_device(request: Request, body: DeviceProvision):
    """Device sends claim code, gets back device_id + api_key."""
    db = request.app.state.db
    result = db.provision_device_by_claim_code(body.claim_code)
    if not result:
        return JSONResponse(
            status_code=404,
            content={"error": "Invalid or unknown claim code"}
        )
    return {
        "device_id": result["device_id"],
        "api_key": result["api_key"],
    }


@router.get("/")
async def list_devices():
    return {"devices": list(devices.values())}
