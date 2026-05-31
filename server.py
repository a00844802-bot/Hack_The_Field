#!/usr/bin/env python3
"""Tractor predictive maintenance demo backend.

Run: python server.py
Open: http://localhost:8000
"""
from __future__ import annotations

import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "tractor_sensors.db"

MODELS = ["8R 410", "7R 330", "6M 155", "9RX 640", "5E 75"]
PARTS = {
    "engine_overheat": {"part": "Cooling package / thermostat kit", "sku": "JD-COOL-4820"},
    "oil_pressure_low": {"part": "Oil filter + pressure sensor", "sku": "JD-OIL-9912"},
    "hydraulic_pressure_drop": {"part": "Hydraulic filter + hose kit", "sku": "JD-HYD-4431"},
    "vibration_high": {"part": "Bearing and mount inspection kit", "sku": "JD-BRG-2240"},
    "battery_low": {"part": "Heavy-duty battery", "sku": "JD-BAT-7710"},
    "dpf_saturation": {"part": "DPF service kit", "sku": "JD-DPF-1500"},
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS machines (
                id TEXT PRIMARY KEY,
                model TEXT NOT NULL,
                customer TEXT NOT NULL,
                dealer_region TEXT NOT NULL,
                hours INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id TEXT NOT NULL,
                ts TEXT NOT NULL,
                engine_temp REAL NOT NULL,
                oil_pressure REAL NOT NULL,
                hydraulic_pressure REAL NOT NULL,
                vibration REAL NOT NULL,
                battery_voltage REAL NOT NULL,
                dpf_load REAL NOT NULL,
                fuel_rate REAL NOT NULL,
                FOREIGN KEY(machine_id) REFERENCES machines(id)
            );
            CREATE TABLE IF NOT EXISTS parts_preparations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id TEXT NOT NULL,
                sku TEXT NOT NULL,
                part TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'prepared',
                created_at TEXT NOT NULL
            );
            """
        )
        count = conn.execute("SELECT COUNT(*) AS c FROM machines").fetchone()["c"]
        if count == 0:
            seed_data(conn)


def seed_data(conn: sqlite3.Connection) -> None:
    random.seed(42)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    machines = []
    for idx in range(1, 13):
        model = random.choice(MODELS)
        machine_id = f"JD-{model.split()[0]}-{1000 + idx}"
        machines.append((machine_id, model, f"Client {idx:02d}", random.choice(["North", "Central", "South", "West"]), random.randint(350, 5400)))
    conn.executemany("INSERT INTO machines VALUES (?, ?, ?, ?, ?)", machines)

    for machine_id, model, customer, region, hours in machines:
        # A few machines are intentionally degrading to demonstrate predictive alerts.
        profile = random.choice(["normal", "hot", "oil", "hydraulic", "vibration", "battery", "dpf"])
        for h in range(168):
            ts = now - timedelta(hours=167 - h)
            t = h / 167
            work_cycle = 1 if 6 <= ts.hour <= 20 else 0.25
            engine_temp = 82 + 11 * work_cycle + random.gauss(0, 2)
            oil_pressure = 48 - 4 * work_cycle + random.gauss(0, 1.2)
            hydraulic_pressure = 3020 - 70 * work_cycle + random.gauss(0, 35)
            vibration = 2.1 + 0.7 * work_cycle + random.gauss(0, 0.18)
            battery_voltage = 12.9 - 0.15 * work_cycle + random.gauss(0, 0.04)
            dpf_load = 34 + 22 * work_cycle + 8 * math.sin(h / 18) + random.gauss(0, 2)
            fuel_rate = 8 + 9 * work_cycle + random.gauss(0, 0.8)
            if profile == "hot":
                engine_temp += 18 * t
            elif profile == "oil":
                oil_pressure -= 13 * t
            elif profile == "hydraulic":
                hydraulic_pressure -= 500 * t
            elif profile == "vibration":
                vibration += 3.0 * t
            elif profile == "battery":
                battery_voltage -= 1.4 * t
            elif profile == "dpf":
                dpf_load += 45 * t
            conn.execute(
                """INSERT INTO readings
                   (machine_id, ts, engine_temp, oil_pressure, hydraulic_pressure, vibration, battery_voltage, dpf_load, fuel_rate)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (machine_id, ts.isoformat(), engine_temp, oil_pressure, hydraulic_pressure, vibration, battery_voltage, dpf_load, fuel_rate),
            )


def slope(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    xbar = (n - 1) / 2
    ybar = sum(values) / n
    denom = sum((i - xbar) ** 2 for i in range(n)) or 1
    return sum((i - xbar) * (v - ybar) for i, v in enumerate(values)) / denom


def analyze_machine(machine: sqlite3.Row, rows: list[sqlite3.Row]) -> dict:
    latest = rows[-1]
    last24 = rows[-24:] if len(rows) >= 24 else rows
    metrics = {
        "engine_temp": [r["engine_temp"] for r in last24],
        "oil_pressure": [r["oil_pressure"] for r in last24],
        "hydraulic_pressure": [r["hydraulic_pressure"] for r in last24],
        "vibration": [r["vibration"] for r in last24],
        "battery_voltage": [r["battery_voltage"] for r in last24],
        "dpf_load": [r["dpf_load"] for r in last24],
    }
    rules = [
        ("engine_overheat", "Engine temperature rising", "engine_temp", 105, "above", "Cooling system may overheat", 5),
        ("oil_pressure_low", "Oil pressure falling", "oil_pressure", 34, "below", "Lubrication risk", 5),
        ("hydraulic_pressure_drop", "Hydraulic pressure dropping", "hydraulic_pressure", 2600, "below", "Hydraulic performance loss", 4),
        ("vibration_high", "Abnormal vibration", "vibration", 4.8, "above", "Bearing, belt, or mount wear", 4),
        ("battery_low", "Battery voltage weakening", "battery_voltage", 11.9, "below", "Starting/charging risk", 3),
        ("dpf_saturation", "DPF load increasing", "dpf_load", 85, "above", "Regeneration/service may be needed", 3),
    ]
    alerts = []
    tendencies = []
    for code, title, metric, threshold, direction, detail, weight in rules:
        current = float(latest[metric])
        m_slope = slope(metrics[metric])
        trend_value = m_slope * 24
        approaching = (direction == "above" and m_slope > 0) or (direction == "below" and m_slope < 0)
        current_fault = current >= threshold if direction == "above" else current <= threshold
        hours_to_threshold = None
        if approaching and abs(m_slope) > 0.01:
            hours_to_threshold = (threshold - current) / m_slope
            if hours_to_threshold < 0:
                hours_to_threshold = 0
        predictive = hours_to_threshold is not None and hours_to_threshold <= 72
        severity = "ok"
        if current_fault:
            severity = "critical"
        elif predictive:
            severity = "warning" if hours_to_threshold <= 36 else "watch"
        if severity != "ok":
            part = PARTS[code]
            confidence = min(0.96, 0.52 + abs(trend_value) / (threshold if threshold else 1) * weight + (0.22 if current_fault else 0))
            alerts.append({
                "machineId": machine["id"],
                "customer": machine["customer"],
                "model": machine["model"],
                "code": code,
                "title": title,
                "severity": severity,
                "detail": detail,
                "metric": metric,
                "current": round(current, 2),
                "threshold": threshold,
                "hoursToThreshold": None if hours_to_threshold is None else round(hours_to_threshold, 1),
                "confidence": round(confidence, 2),
                "recommendedPart": part["part"],
                "sku": part["sku"],
            })
        tendencies.append({
            "metric": metric,
            "current": round(current, 2),
            "trend24h": round(trend_value, 2),
            "direction": "up" if trend_value > 0.4 else "down" if trend_value < -0.4 else "stable",
        })
    risk_score = min(100, round(sum({"critical": 32, "warning": 20, "watch": 10}.get(a["severity"], 0) for a in alerts) + machine["hours"] / 180))
    status = "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy"
    return {"machine": dict(machine), "latest": dict(latest), "alerts": alerts, "tendencies": tendencies, "riskScore": risk_score, "status": status}


def get_analysis() -> dict:
    with connect() as conn:
        machines = conn.execute("SELECT * FROM machines ORDER BY id").fetchall()
        fleet = []
        all_alerts = []
        for machine in machines:
            rows = conn.execute("SELECT * FROM readings WHERE machine_id=? ORDER BY ts", (machine["id"],)).fetchall()
            analyzed = analyze_machine(machine, rows)
            fleet.append(analyzed)
            all_alerts.extend(analyzed["alerts"])
        all_alerts.sort(key=lambda a: {"critical": 0, "warning": 1, "watch": 2}.get(a["severity"], 3))
        part_forecast = {}
        for alert in all_alerts:
            key = alert["sku"]
            part_forecast.setdefault(key, {"sku": key, "part": alert["recommendedPart"], "quantity": 0, "machines": []})
            part_forecast[key]["quantity"] += 1
            part_forecast[key]["machines"].append(alert["machineId"])
        usage_by_region = {}
        for item in fleet:
            region = item["machine"]["dealer_region"]
            usage_by_region.setdefault(region, {"region": region, "machines": 0, "hours": 0, "avgRisk": 0})
            usage_by_region[region]["machines"] += 1
            usage_by_region[region]["hours"] += item["machine"]["hours"]
            usage_by_region[region]["avgRisk"] += item["riskScore"]
        for v in usage_by_region.values():
            v["avgRisk"] = round(v["avgRisk"] / max(v["machines"], 1), 1)
        return {
            "generatedAt": datetime.now().isoformat(timespec="seconds"),
            "fleet": fleet,
            "alerts": all_alerts,
            "dealer": {
                "summary": {
                    "machines": len(fleet),
                    "critical": sum(1 for a in all_alerts if a["severity"] == "critical"),
                    "predictive": sum(1 for a in all_alerts if a["severity"] in ("warning", "watch")),
                    "healthy": sum(1 for f in fleet if f["status"] == "healthy"),
                },
                "usageByRegion": sorted(usage_by_region.values(), key=lambda r: r["region"]),
                "partsForecast": sorted(part_forecast.values(), key=lambda p: -p["quantity"]),
            },
        }


def add_sensor_reading(body: dict) -> dict:
    """Accept one live telemetry reading from a demo device and re-run analysis."""
    machine_id = body.get("machineId") or body.get("machine_id")
    if not machine_id:
        return {"error": "Missing machineId"}, 400

    fields = [
        "engine_temp",
        "oil_pressure",
        "hydraulic_pressure",
        "vibration",
        "battery_voltage",
        "dpf_load",
        "fuel_rate",
    ]
    missing = [f for f in fields if body.get(f) is None]
    if missing:
        return {"error": f"Missing sensor fields: {', '.join(missing)}"}, 400

    try:
        values = {f: float(body[f]) for f in fields}
    except (TypeError, ValueError):
        return {"error": "All sensor fields must be numbers"}, 400

    ts = body.get("ts") or datetime.now().isoformat(timespec="seconds")
    with connect() as conn:
        machine = conn.execute("SELECT * FROM machines WHERE id=?", (machine_id,)).fetchone()
        if not machine:
            return {"error": f"Machine not found: {machine_id}"}, 404
        conn.execute(
            """INSERT INTO readings
               (machine_id, ts, engine_temp, oil_pressure, hydraulic_pressure, vibration, battery_voltage, dpf_load, fuel_rate)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                machine_id,
                ts,
                values["engine_temp"],
                values["oil_pressure"],
                values["hydraulic_pressure"],
                values["vibration"],
                values["battery_voltage"],
                values["dpf_load"],
                values["fuel_rate"],
            ),
        )
        rows = conn.execute("SELECT * FROM readings WHERE machine_id=? ORDER BY ts", (machine_id,)).fetchall()
        analyzed = analyze_machine(machine, rows)
    return {
        "ok": True,
        "message": f"Telemetry accepted for {machine_id}",
        "machine": analyzed,
        "alerts": analyzed["alerts"],
    }, 201


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _json(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/analysis":
            return self._json(get_analysis())
        if parsed.path.startswith("/api/machines/"):
            machine_id = parsed.path.split("/")[-1]
            data = get_analysis()
            match = next((m for m in data["fleet"] if m["machine"]["id"] == machine_id), None)
            return self._json(match or {"error": "Machine not found"}, 200 if match else 404)
        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "Invalid JSON body"}, 400)

        if parsed.path == "/api/readings":
            data, status = add_sensor_reading(body)
            return self._json(data, status)

        if parsed.path == "/api/prepare-part":
            required = ["machineId", "sku", "part", "reason"]
            if not all(body.get(k) for k in required):
                return self._json({"error": "Missing required fields"}, 400)
            with connect() as conn:
                conn.execute(
                    "INSERT INTO parts_preparations (machine_id, sku, part, reason, created_at) VALUES (?, ?, ?, ?, ?)",
                    (body["machineId"], body["sku"], body["part"], body["reason"], datetime.now().isoformat(timespec="seconds")),
                )
            return self._json({"ok": True, "message": f"Prepared {body['part']} for {body['machineId']}"})

        return self._json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"Serving predictive maintenance dashboard on http://localhost:{port}")
    ThreadingHTTPServer(("", port), Handler).serve_forever()
