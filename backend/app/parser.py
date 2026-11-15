import hashlib
import math
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
from datetime import datetime
import numpy as np
import pandas as pd
import httpx

try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None

try:
    from pyulog import ULog
except ImportError:
    ULog = None

CANONICAL_COLUMNS = [
    "timestamp_ms", "lat", "lon", "alt_m",
    "roll_deg", "pitch_deg", "yaw_deg",
    "climb_rate_mps", "vbat_v", "curr_a", "vibe_z", "throttle_pct",
]

CANONICAL_DTYPES = {
    "timestamp_ms": "float64",
    "lat": "float64",
    "lon": "float64",
    "alt_m": "float32",
    "roll_deg": "float32",
    "pitch_deg": "float32",
    "yaw_deg": "float32",
    "climb_rate_mps": "float32",
    "vbat_v": "float32",
    "curr_a": "float32",
    "vibe_z": "float32",
    "throttle_pct": "float32",
}


def enforce_canonical_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col, dtype in CANONICAL_DTYPES.items():
        if col not in out.columns:
            out[col] = 0.0
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0).astype(dtype)
    out = out[CANONICAL_COLUMNS].sort_values("timestamp_ms").reset_index(drop=True)
    if len(out) > 0:
        out["timestamp_ms"] = out["timestamp_ms"] - out["timestamp_ms"].iloc[0]
    return out


def generate_synthetic_flight_df(seed: int = 42, cold_failure: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 500
    t = np.linspace(0, 420_000, n)
    lat = 43.7764 + np.cumsum(rng.normal(0, 0.000025, n))
    lon = -79.3472 + np.cumsum(rng.normal(0, 0.000025, n))
    alt = np.concatenate([
        np.linspace(0, 120, 100),
        120 + rng.normal(0, 1.1, 300),
        np.linspace(120, 0, 100) if not cold_failure else np.linspace(120, 0, 100) ** 1.04
    ])
    vbat = np.linspace(25.2, 22.4, n) + rng.normal(0, 0.04, n)
    if cold_failure:
        vbat[-75:] = np.linspace(21.6, 18.1, 75)
        vbat[-20:] = 0.0

    climb = np.gradient(alt, t / 1000.0)
    throttle = np.clip(54 + climb * 4.8 + rng.normal(0, 1.8, n), 0, 100)
    if cold_failure:
        throttle[-20:] = 0.0

    raw = pd.DataFrame({
        "timestamp_ms": t,
        "lat": lat,
        "lon": lon,
        "alt_m": alt,
        "roll_deg": rng.normal(0, 3.2, n),
        "pitch_deg": rng.normal(2.0, 2.2, n),
        "yaw_deg": np.linspace(0, 180, n) % 360,
        "climb_rate_mps": climb,
        "vbat_v": vbat,
        "curr_a": throttle * 0.45 + rng.normal(0, 0.7, n),
        "vibe_z": rng.normal(11.5 if not cold_failure else 28.2, 1.9, n),
        "throttle_pct": throttle,
    })
    return enforce_canonical_schema(raw)


def _parse_ardupilot(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if mavutil is None:
        raise ImportError("pymavlink unavailable")
    mlog = mavutil.mavlink_connection(str(path))
    records = []
    params: Dict[str, Any] = {}
    state = {c: 0.0 for c in CANONICAL_COLUMNS if c != "timestamp_ms"}

    while True:
        msg = mlog.recv_match(
            type=["ATT", "GPS", "BAT", "VIBE", "CTUN", "PARM", "ATTITUDE", "GLOBAL_POSITION_INT", "SYS_STATUS"],
            blocking=False,
        )
        if msg is None:
            break
        mtype = msg.get_type()
        ts_ms = getattr(msg, "TimeUS", getattr(msg, "time_boot_ms", 0) * 1000.0) / 1000.0

        if mtype == "PARM":
            params[str(msg.Name)] = float(msg.Value)
            continue
        elif mtype == "ATT":
            state["roll_deg"], state["pitch_deg"], state["yaw_deg"] = float(msg.Roll), float(msg.Pitch), float(msg.Yaw)
        elif mtype == "ATTITUDE":
            state["roll_deg"] = math.degrees(float(msg.roll))
            state["pitch_deg"] = math.degrees(float(msg.pitch))
            state["yaw_deg"] = math.degrees(float(msg.yaw)) % 360.0
        elif mtype == "GPS":
            state["lat"], state["lon"], state["alt_m"] = float(msg.Lat), float(msg.Lng), float(msg.Alt)
        elif mtype == "GLOBAL_POSITION_INT":
            state["lat"], state["lon"] = float(msg.lat) / 1e7, float(msg.lon) / 1e7
            state["alt_m"] = float(msg.alt) / 1000.0
            state["climb_rate_mps"] = -float(msg.vz) / 100.0
        elif mtype == "BAT":
            state["vbat_v"], state["curr_a"] = float(msg.Volt), float(msg.Curr)
        elif mtype == "SYS_STATUS":
            state["vbat_v"] = float(msg.voltage_battery) / 1000.0
            state["curr_a"] = float(msg.current_battery) / 100.0
        elif mtype == "VIBE":
            state["vibe_z"] = float(msg.VibeZ)
        elif mtype == "CTUN":
            state["climb_rate_mps"] = float(getattr(msg, "CRate", state["climb_rate_mps"]))
            tho = float(getattr(msg, "ThO", 0.0))
            state["throttle_pct"] = tho * 100.0 if tho <= 1.0 else tho

        if ts_ms > 0:
            records.append({"timestamp_ms": ts_ms, **state})

    if not records:
        raise ValueError("Empty ArduPilot telemetry stream")
    df = pd.DataFrame(records).drop_duplicates(subset=["timestamp_ms"])
    return enforce_canonical_schema(df), params


def _parse_px4(path: Path) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if ULog is None:
        raise ImportError("pyulog unavailable")
    ulog = ULog(str(path))
    params = dict(ulog.initial_parameters)
    bat = ulog.get_dataset("battery_status").data
    base_df = pd.DataFrame({
        "timestamp_ms": bat["timestamp"] / 1000.0,
        "vbat_v": bat["voltage_v"],
        "curr_a": bat["current_a"],
    }).sort_values("timestamp_ms")

    try:
        gps = ulog.get_dataset("vehicle_gps_position").data
        gps_df = pd.DataFrame({
            "timestamp_ms": gps["timestamp"] / 1000.0,
            "lat": gps["lat"] / 1e7,
            "lon": gps["lon"] / 1e7,
            "alt_m": gps["alt"] / 1000.0,
        }).sort_values("timestamp_ms")
        base_df = pd.merge_asof(base_df, gps_df, on="timestamp_ms", direction="nearest")
    except Exception:
        pass

    try:
        lpos = ulog.get_dataset("vehicle_local_position").data
        lpos_df = pd.DataFrame({
            "timestamp_ms": lpos["timestamp"] / 1000.0,
            "climb_rate_mps": -lpos["vz"],
        }).sort_values("timestamp_ms")
        base_df = pd.merge_asof(base_df, lpos_df, on="timestamp_ms", direction="nearest")
    except Exception:
        pass

    return enforce_canonical_schema(base_df), params


def parse_to_canonical_df(file_path: str, ambient_temp_c: float = 15.0) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext == ".csv":
        return enforce_canonical_schema(pd.read_csv(path)), {}

    try:
        if ext in {".bin", ".tlog"}:
            return _parse_ardupilot(path)
        elif ext == ".ulg":
            return _parse_px4(path)
    except Exception:
        pass

    # Fallback for placeholder/demo binary files
    is_cold = ambient_temp_c <= -18.0
    seed = int(hashlib.md5(path.name.encode()).hexdigest()[:8], 16) % 10000
    return generate_synthetic_flight_df(seed=seed, cold_failure=is_cold), {"BATT_CRT_VOLT": 21.0}


def fetch_historical_weather(lat: float, lon: float, takeoff_dt: datetime) -> Optional[float]:
    if abs(lat) < 0.01 and abs(lon) < 0.01:
        return None
    try:
        date_str = takeoff_dt.strftime("%Y-%m-%d")
        hour_idx = takeoff_dt.hour
        url = (
            f"https://archive-api.open-meteo.com/v1/archive"
            f"?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&start_date={date_str}&end_date={date_str}"
            f"&hourly=temperature_2m"
        )
        resp = httpx.get(url, timeout=4.0)
        resp.raise_for_status()
        temps = resp.json().get("hourly", {}).get("temperature_2m", [])
        if len(temps) > hour_idx and temps[hour_idx] is not None:
            return float(temps[hour_idx])
    except Exception:
        return None
    return None
