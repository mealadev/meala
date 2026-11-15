from datetime import datetime
from typing import Dict, Any, List, Optional
from pydantic import BaseModel


class FlightSummary(BaseModel):
    flight_id: str
    vehicle_uid: str
    battery_uid: Optional[str] = None
    autopilot_type: str
    pilot: Optional[str] = None
    takeoff_time: datetime
    duration_sec: int
    takeoff_lat: float
    takeoff_lon: float
    min_battery_v: float
    max_vibe_z: float
    ambient_temp_c: float
    had_alert: bool
    status: str
    notes: str
    parameters_json: Dict[str, Any] = {}

    class Config:
        from_attributes = True


class FlightSeriesResponse(BaseModel):
    flight_id: str
    vehicle_uid: str
    autopilot_type: str
    ambient_temp_c: float
    t_sec: List[float]
    vbat_v: List[float]
    alt_m: List[float]
    climb_rate_mps: List[float]
    vibe_z: List[float]
    throttle_pct: List[float]
    lat: List[float]
    lon: List[float]


class UploadQueuedResponse(BaseModel):
    flight_id: str
    status: str
    message: str
