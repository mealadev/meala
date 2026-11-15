from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from .database import Base


class Flight(Base):
    __tablename__ = "flights"

    flight_id = Column(String(32), primary_key=True, index=True)
    vehicle_uid = Column(String(64), index=True, nullable=False)
    battery_uid = Column(String(64), index=True, nullable=True)
    autopilot_type = Column(String(32), index=True, nullable=False)
    pilot = Column(String(64), index=True, nullable=True)
    takeoff_time = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)
    duration_sec = Column(Integer, default=0)
    takeoff_lat = Column(Float, default=0.0)
    takeoff_lon = Column(Float, default=0.0)
    min_battery_v = Column(Float, default=0.0)
    max_vibe_z = Column(Float, default=0.0)
    ambient_temp_c = Column(Float, default=15.0, index=True)
    had_alert = Column(Boolean, default=False, index=True)
    status = Column(String(24), default="READY", index=True)
    notes = Column(Text, default="")
    parameters_json = Column(JSON, default=dict)
    raw_log_path = Column(String(255), nullable=True)
    parquet_path = Column(String(255), nullable=True)
