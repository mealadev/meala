import os
import uuid
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, Depends, UploadFile, File, Form, HTTPException, Header, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_

from .config import settings
from .database import Base, engine, get_db, SessionLocal
from .models import Flight
from .schemas import FlightSummary, FlightSeriesResponse, UploadQueuedResponse
from .parser import parse_to_canonical_df, fetch_historical_weather

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Meala Telemetry API",
    description="Self-hosted UAV flight log ingestion, SQL metadata index, and Apache Parquet streaming API.",
    version="1.0.0",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    if settings.org_api_key and x_api_key != settings.org_api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


def _process_flight_background(flight_id: str, enrich_weather: bool = True):
    db = SessionLocal()
    try:
        flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
        if not flight or not flight.raw_log_path:
            return

        df, extracted_params = parse_to_canonical_df(
            flight.raw_log_path,
            ambient_temp_c=flight.ambient_temp_c or 15.0,
        )
        os.makedirs(settings.parquet_dir, exist_ok=True)
        pq_path = str(Path(settings.parquet_dir) / f"{flight_id}.parquet")
        df.to_parquet(pq_path, index=False, compression="snappy")

        valid_v = df["vbat_v"][df["vbat_v"] > 1.0]
        min_v = float(valid_v.min()) if len(valid_v) > 0 else 0.0
        max_vibe = float(df["vibe_z"].max()) if len(df) > 0 else 0.0
        duration_sec = int((df["timestamp_ms"].max() - df["timestamp_ms"].min()) / 1000.0) if len(df) > 1 else 0
        lat = float(df["lat"].iloc[0]) if len(df) > 0 else 0.0
        lon = float(df["lon"].iloc[0]) if len(df) > 0 else 0.0

        temp_c = flight.ambient_temp_c
        if enrich_weather and flight.takeoff_time:
            fetched_temp = fetch_historical_weather(lat, lon, flight.takeoff_time)
            if fetched_temp is not None:
                temp_c = fetched_temp

        had_alert = bool(min_v < 20.0 or max_vibe > 25.0 or (df["vbat_v"] == 0.0).any())

        flight.duration_sec = duration_sec
        flight.takeoff_lat = lat
        flight.takeoff_lon = lon
        flight.min_battery_v = round(min_v, 2)
        flight.max_vibe_z = round(max_vibe, 2)
        flight.ambient_temp_c = float(temp_c)
        flight.had_alert = had_alert
        flight.parameters_json = {**(flight.parameters_json or {}), **extracted_params}
        flight.parquet_path = pq_path
        flight.status = "READY"
        db.commit()
    except Exception as exc:
        flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
        if flight:
            flight.status = "FAILED"
            flight.notes = f"{flight.notes} [Ingest error: {exc}]".strip()
            db.commit()
    finally:
        db.close()


def _seed_initial_data():
    if not settings.seed_demo_flights:
        return
    db = SessionLocal()
    try:
        if db.query(Flight).count() > 0:
            return
        os.makedirs(settings.raw_logs_dir, exist_ok=True)
        samples = [
            ("FLT-2019-0114", "flight_jan_2019.bin", "TailSitter-VTOL-01", "BAT-6S-002", "ArduPilot", "Fiona M.",
             datetime(2019, 1, 14, 9, 42, tzinfo=timezone.utc), -21.5,
             "Cold weather electrolytic capacitor voltage spike failure.", {"BATT_CRT_VOLT": 21.0, "INS_ACCEL_FILTER": 20}),
            ("FLT-2019-1219", "flight_dec_2019.bin", "TailSitter-VTOL-01", "BAT-6S-005", "ArduPilot", "Tim R.",
             datetime(2019, 12, 19, 10, 15, tzinfo=timezone.utc), -20.2,
             "Repeated winter shutdown before Christmas.", {"BATT_CRT_VOLT": 21.0, "INS_ACCEL_FILTER": 20}),
            ("FLT-2026-0208", "flight_feb_2026.ulg", "TailSitter-VTOL-02", "BAT-6S-011", "PX4", "Brandon H.",
             datetime(2026, 2, 8, 14, 10, tzinfo=timezone.utc), -17.0,
             "Upgraded to solid polymer ESC capacitors. Nominal flight.", {"BAT1_V_CRIT": 21.0, "MC_ROLL_P": 6.5}),
            ("FLT-2026-0514", "flight_may_2026.tlog", "Mapper-Quad-04", "BAT-4S-019", "ArduPilot", "Brandon H.",
             datetime(2026, 5, 14, 11, 20, tzinfo=timezone.utc), 18.4,
             "PID tuning flight; roll/pitch solid, yaw needs slightly more D.", {"ATC_RAT_RLL_P": 0.135, "ATC_RAT_YAW_D": 0.004}),
        ]
        for fid, fname, veh, bat, stack, pilot, dt, temp, notes, params in samples:
            raw_path = str(Path(settings.raw_logs_dir) / fname)
            Path(raw_path).write_text("DEMO_PLACEHOLDER", encoding="utf-8")
            fl = Flight(
                flight_id=fid,
                vehicle_uid=veh,
                battery_uid=bat,
                autopilot_type=stack,
                pilot=pilot,
                takeoff_time=dt,
                ambient_temp_c=temp,
                notes=notes,
                parameters_json=params,
                raw_log_path=raw_path,
                status="PROCESSING",
            )
            db.add(fl)
            db.commit()
            _process_flight_background(fid, enrich_weather=False)
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    _seed_initial_data()


@app.get("/api/v1/health")
def health_check():
    return {"status": "ok", "service": "meala-api", "version": "1.0.0"}


@app.post("/api/v1/flights/upload", response_model=UploadQueuedResponse, status_code=202)
async def upload_flight_log(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    vehicle_uid: str = Form("TailSitter-VTOL-01"),
    battery_uid: str = Form("BAT-6S-001"),
    autopilot_type: str = Form("ArduPilot"),
    pilot: str = Form("Brandon"),
    ambient_temp_c: Optional[float] = Form(None),
    notes: str = Form(""),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    if x_api_key is not None:
        verify_api_key(x_api_key)

    flight_id = f"FLT-{uuid.uuid4().hex[:8].upper()}"
    os.makedirs(settings.raw_logs_dir, exist_ok=True)
    safe_name = f"{flight_id}_{Path(file.filename or 'log.bin').name}"
    raw_path = str(Path(settings.raw_logs_dir) / safe_name)

    with open(raw_path, "wb") as out_f:
        shutil.copyfileobj(file.file, out_f)

    flight = Flight(
        flight_id=flight_id,
        vehicle_uid=vehicle_uid,
        battery_uid=battery_uid,
        autopilot_type=autopilot_type,
        pilot=pilot,
        takeoff_time=datetime.now(timezone.utc),
        ambient_temp_c=ambient_temp_c if ambient_temp_c is not None else 15.0,
        notes=notes,
        raw_log_path=raw_path,
        status="PROCESSING",
    )
    db.add(flight)
    db.commit()

    background_tasks.add_task(_process_flight_background, flight_id, ambient_temp_c is None)
    return UploadQueuedResponse(
        flight_id=flight_id,
        status="PROCESSING",
        message="Flight log accepted and queued for Parquet normalization.",
    )


@app.get("/api/v1/flights", response_model=List[FlightSummary])
def list_flights(
    autopilot_type: Optional[str] = Query(None),
    max_temp_c: Optional[float] = Query(None),
    only_alerts: bool = Query(False),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(Flight)
    if autopilot_type:
        query = query.filter(Flight.autopilot_type == autopilot_type)
    if max_temp_c is not None:
        query = query.filter(Flight.ambient_temp_c <= max_temp_c)
    if only_alerts:
        query = query.filter(Flight.had_alert.is_(True))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Flight.flight_id.ilike(like),
                Flight.vehicle_uid.ilike(like),
                Flight.battery_uid.ilike(like),
                Flight.pilot.ilike(like),
                Flight.notes.ilike(like),
            )
        )
    return query.order_by(Flight.takeoff_time.desc()).limit(250).all()


@app.get("/api/v1/flights/{flight_id}", response_model=FlightSummary)
def get_flight(flight_id: str, db: Session = Depends(get_db)):
    flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    return flight


@app.get("/api/v1/flights/{flight_id}/series", response_model=FlightSeriesResponse)
def get_flight_series(
    flight_id: str,
    max_points: int = Query(400, ge=50, le=2000),
    db: Session = Depends(get_db),
):
    flight = db.query(Flight).filter(Flight.flight_id == flight_id).first()
    if not flight:
        raise HTTPException(status_code=404, detail="Flight not found")
    if flight.status != "READY" or not flight.parquet_path or not os.path.exists(flight.parquet_path):
        raise HTTPException(status_code=409, detail=f"Flight telemetry not ready (status={flight.status})")

    df = pd.read_parquet(flight.parquet_path)
    if len(df) > max_points:
        idx = np.linspace(0, len(df) - 1, max_points, dtype=int)
        df = df.iloc[idx]

    return FlightSeriesResponse(
        flight_id=flight.flight_id,
        vehicle_uid=flight.vehicle_uid,
        autopilot_type=flight.autopilot_type,
        ambient_temp_c=flight.ambient_temp_c,
        t_sec=(df["timestamp_ms"] / 1000.0).round(2).tolist(),
        vbat_v=df["vbat_v"].round(2).tolist(),
        alt_m=df["alt_m"].round(2).tolist(),
        climb_rate_mps=df["climb_rate_mps"].round(2).tolist(),
        vibe_z=df["vibe_z"].round(2).tolist(),
        throttle_pct=df["throttle_pct"].round(1).tolist(),
        lat=df["lat"].round(6).tolist(),
        lon=df["lon"].round(6).tolist(),
    )
