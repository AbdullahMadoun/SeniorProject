from fastapi import APIRouter, HTTPException
from typing import List, Optional, Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hardware", tags=["hardware"])

_hardware_manager = None
_health_monitor = None
_watchdog = None


def set_hardware_manager(manager) -> None:
    global _hardware_manager
    _hardware_manager = manager


def set_health_monitor(monitor) -> None:
    global _health_monitor
    _health_monitor = monitor


def set_watchdog(watchdog_timer) -> None:
    global _watchdog
    _watchdog = watchdog_timer


@router.get("/status")
async def get_hardware_status() -> Dict[str, Any]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    devices = _hardware_manager.get_all_devices()
    statuses = []

    for device in devices:
        status = device.status
        statuses.append(status.to_dict())

    return {
        "global_health": _hardware_manager.get_global_health().value,
        "total_devices": len(devices),
        "devices": statuses,
    }


@router.get("/status/{device_id}")
async def get_device_status(device_id: str) -> Dict[str, Any]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    device = _hardware_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    return device.status.to_dict()


@router.post("/boot")
async def boot_all_devices() -> Dict[str, Any]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    report = _hardware_manager.boot_all()

    return {
        "total_devices": report.total_devices,
        "successful": report.successful,
        "failed": report.failed,
        "skipped": report.skipped,
        "boot_time": report.boot_time,
        "device_results": report.device_results,
        "device_messages": report.device_messages,
    }


@router.post("/shutdown")
async def shutdown_all_devices() -> Dict[str, bool]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    return _hardware_manager.shutdown_all()


@router.post("/emergency-stop")
async def emergency_stop() -> Dict[str, str]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    _hardware_manager.emergency_stop_all()
    return {"status": "emergency_stop_executed"}


@router.get("/health/events")
async def get_health_events(limit: int = 50) -> List[Dict[str, Any]]:
    if not _health_monitor:
        raise HTTPException(status_code=503, detail="Health monitor not initialized")

    events = _health_monitor.get_recent_events(limit=limit)
    return [event.to_dict() for event in events]


@router.get("/health/events/{device_id}")
async def get_device_health_events(device_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    if not _health_monitor:
        raise HTTPException(status_code=503, detail="Health monitor not initialized")

    events = _health_monitor.get_events_by_device(device_id, limit=limit)
    return [event.to_dict() for event in events]


@router.get("/health/history/{device_id}")
async def get_device_health_history(device_id: str) -> List[str]:
    if not _health_monitor:
        raise HTTPException(status_code=503, detail="Health monitor not initialized")

    history = _health_monitor.get_device_health_history(device_id)
    return [h.value for h in history]


@router.get("/watchdog")
async def get_watchdog_status() -> Dict[str, Any]:
    if not _watchdog:
        raise HTTPException(status_code=503, detail="Watchdog not initialized")

    registered = _watchdog.get_registered_devices()
    status = {}

    for device_id in registered:
        remaining = _watchdog.get_time_remaining(device_id)
        status[device_id] = {
            "time_remaining": remaining,
            "registered": True,
        }

    return {
        "registered_devices": registered,
        "device_status": status,
    }


@router.post("/watchdog/kick/{device_id}")
async def kick_watchdog(device_id: str) -> Dict[str, bool]:
    if not _watchdog:
        raise HTTPException(status_code=503, detail="Watchdog not initialized")

    success = _watchdog.kick(device_id)
    return {"success": success}


@router.get("/devices/by-type/{device_type}")
async def get_devices_by_type(device_type: str) -> List[Dict[str, Any]]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    devices = _hardware_manager.get_devices_by_type(device_type)
    return [device.status.to_dict() for device in devices]


@router.get("/devices/by-health/{health_status}")
async def get_devices_by_health(health_status: str) -> List[Dict[str, Any]]:
    if not _hardware_manager:
        raise HTTPException(status_code=503, detail="Hardware manager not initialized")

    from hal.base import HealthStatus

    try:
        status = HealthStatus(health_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid health status: {health_status}")

    devices = _hardware_manager.get_devices_by_health(status)
    return [device.status.to_dict() for device in devices]


def create_hardware_dashboard_app(profile_name: str = "simulation"):
    from fastapi import FastAPI
    import asyncio

    app = FastAPI(title="Hardware Dashboard API")

    try:
        from autonomy.companion.hal.manager import HardwareManager
        from autonomy.companion.hal.health import HealthMonitor
        from autonomy.companion.hal.watchdog import WatchdogTimer
        from autonomy.companion.hal.drivers.mock_driver import (
            MockGPSDevice,
            MockRangefinderDevice,
            MockADCDevice,
            MockCameraDevice,
            MockMAVLinkDevice,
            MockGPIODevice,
        )
        from autonomy.companion.config import load_default_profile

        manager = HardwareManager()
        monitor = HealthMonitor(check_interval=5.0)
        watchdog = WatchdogTimer(timeout=30.0, tick_interval=5.0)

        profile = load_default_profile(profile_name)

        for device_config in profile.get_enabled_devices():
            if device_config.device_type == "gps":
                device = MockGPSDevice(device_config.device_id, device_config.i2c_address or 0x42)
            elif device_config.device_type == "rangefinder":
                device = MockRangefinderDevice(
                    device_config.device_id,
                    device_config.i2c_address or 0x10,
                    min_distance=device_config.min_distance,
                    max_distance=device_config.max_distance,
                )
            elif device_config.device_type == "adc":
                device = MockADCDevice(device_config.device_id, device_config.i2c_address or 0x48)
            elif device_config.device_type == "camera":
                device = MockCameraDevice(device_config.device_id, device_config.camera_index)
            elif device_config.device_type == "mavlink":
                device = MockMAVLinkDevice(device_config.device_id, device_config.connection_string or "tcp:localhost:5760")
            elif device_config.device_type == "gpio":
                device = MockGPIODevice(device_config.device_id, device_config.gpio_pin or 17, device_config.gpio_direction)
            else:
                continue

            manager.register(device)
            watchdog.register(device_config.device_id, timeout=30.0)

        monitor.set_manager(manager)
        manager.boot_all()
        monitor.start()
        watchdog.start()

        set_hardware_manager(manager)
        set_health_monitor(monitor)
        set_watchdog(watchdog)

    except ImportError as e:
        logger.warning(f"Could not import HAL modules: {e}")
        logger.warning("Running in standalone mode without hardware")

    app.include_router(router)

    return app
