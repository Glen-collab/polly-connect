"""
Device management endpoints for Polly Connect
Handles device registration, status, and configuration
"""

from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

router = APIRouter()

# In-memory device registry (swap for database in production)
devices: Dict[str, dict] = {}


class DeviceRegister(BaseModel):
    device_id: str
    firmware_version: Optional[str] = None
    hardware_version: Optional[str] = None


class DeviceConfig(BaseModel):
    """Configuration pushed to device."""
    wake_word_sensitivity: float = 0.5
    silence_timeout_ms: int = 1000
    sample_rate: int = 16000
    server_url: Optional[str] = None


@router.post("/register")
async def register_device(request: Request, device: DeviceRegister):
    """Register a new device or update existing."""
    
    devices[device.device_id] = {
        "device_id": device.device_id,
        "firmware_version": device.firmware_version,
        "hardware_version": device.hardware_version,
        "registered_at": datetime.utcnow().isoformat(),
        "last_seen": datetime.utcnow().isoformat(),
        "status": "online"
    }
    
    return {
        "message": "Device registered",
        "device_id": device.device_id,
        "config": DeviceConfig().dict()
    }


@router.get("/")
async def list_devices():
    """List all registered devices."""
    return {"devices": list(devices.values()), "count": len(devices)}


@router.get("/{device_id}")
async def get_device(device_id: str):
    """Get device details."""
    if device_id not in devices:
        raise HTTPException(status_code=404, detail="Device not found")
    return devices[device_id]


@router.post("/{device_id}/heartbeat")
async def device_heartbeat(device_id: str):
    """Update device last seen time."""
    if device_id not in devices:
        # Auto-register on heartbeat
        devices[device_id] = {
            "device_id": device_id,
            "registered_at": datetime.utcnow().isoformat(),
            "status": "online"
        }
    
    devices[device_id]["last_seen"] = datetime.utcnow().isoformat()
    devices[device_id]["status"] = "online"
    
    return {"status": "ok"}


@router.get("/{device_id}/config")
async def get_device_config(device_id: str):
    """Get configuration for a device."""
    # Could be customized per-device in the future
    return DeviceConfig().dict()


@router.delete("/{device_id}")
async def remove_device(device_id: str):
    """Remove a device from registry."""
    if device_id in devices:
        del devices[device_id]
        return {"message": "Device removed"}
    raise HTTPException(status_code=404, detail="Device not found")
