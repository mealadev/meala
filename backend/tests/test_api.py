import os
os.environ["DATABASE_URL"] = "sqlite:///./test_meala_api.db"
os.environ["RAW_LOGS_DIR"] = "./test_data/raw"
os.environ["PARQUET_DIR"] = "./test_data/parquet"
os.environ["SEED_DEMO_FLIGHTS"] = "true"

from fastapi.testclient import TestClient
from app.main import app, _seed_initial_data

_seed_initial_data()
client = TestClient(app)


def test_health_and_seeded_flights():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    flights = client.get("/api/v1/flights").json()
    assert len(flights) >= 4

    cold = client.get("/api/v1/flights?max_temp_c=-18").json()
    assert all(f["ambient_temp_c"] <= -18.0 for f in cold)


def test_series_endpoint():
    r = client.get("/api/v1/flights/FLT-2019-0114/series")
    assert r.status_code == 200
    body = r.json()
    assert body["flight_id"] == "FLT-2019-0114"
    assert len(body["t_sec"]) > 0
    assert len(body["vbat_v"]) == len(body["t_sec"])
