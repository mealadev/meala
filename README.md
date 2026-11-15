# Meala Self-Hosted Server (`mealadev/meala`)

**Open-source multi-user flight log database, cross-stack telemetry normalizer, and fleet analytics platform for UAV teams.**

Part of the [Meala](https://meala.dev) ecosystem (`github.com/mealadev`).

---

## Architecture

* **`meala-postgres` (PostgreSQL 16):** Stores flight summary rows, anomaly flags, historical takeoff weather, and firmware controller parameters (`JSONB`).
* **`meala-api` (FastAPI + Python 3.12):** Asynchronous background ingestion worker that parses ArduPilot (`.bin`, `.tlog`), PX4 (`.ulg`), and `.csv` logs via `pymavlink`/`pyulog`, normalizes them to Snappy-compressed Apache Parquet files, and enriches takeoff weather via Open-Meteo.
* **`meala-web` (Nginx + Multi-Log Dashboard):** Interactive SQL filter sidebar, 4-flight cross-stack overlay charts (Voltage, Climb Rate, Z-Axis Vibration, Altitude), Leaflet GPS ground tracks, and parameter inspector.

---

## Quickstart (Docker Compose)

```bash
git clone https://github.com/mealadev/meala.git
cd meala
cp .env.example .env
docker compose up --build -d
```

* **Web Dashboard:** `http://localhost:8080`
* **API & OpenAPI Swagger Docs:** `http://localhost:8000/docs`

---

## Hardware & CLI Auto-Ingestion (`X-API-Key`)

```bash
curl -X POST http://localhost:8000/api/v1/flights/upload \
  -H "X-API-Key: change_me_org_ingestion_key" \
  -F "file=@flight_042.bin" \
  -F "vehicle_uid=TailSitter-VTOL-01" \
  -F "battery_uid=BAT-6S-009" \
  -F "autopilot_type=ArduPilot" \
  -F "pilot=Brandon"
```

## License

MIT — see [meala.dev](https://meala.dev) for documentation.
