"""
Device management endpoints
"""

from datetime import datetime
from typing import Dict
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()
devices: Dict[str, dict] = {}


class DeviceRegister(BaseModel):
    device_id: str


@router.post("/register")
async def register_device(device: DeviceRegister):
    devices[device.device_id] = {
        "device_id": device.device_id,
        "registered_at": datetime.utcnow().isoformat(),
        "status": "online"
    }
    return {"message": "Registered", "device_id": device.device_id}


@router.get("/")
async def list_devices():
    return {"devices": list(devices.values())}
