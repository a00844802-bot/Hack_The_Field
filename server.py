#!/usr/bin/env python3
"""Tractor predictive maintenance demo backend.

Run: python server.py
Open: http://<your-ip>:8000 from other devices on the same network
"""
from __future__ import annotations

import json
import math
import base64
import hashlib
import os
import random
import socketserver
import sqlite3
import struct
import threading
import unicodedata
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
from urllib import error as urlerror
from urllib import request as urlrequest

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DB_PATH = BASE_DIR / "tractor_sensors.db"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_TIMEOUT_SECONDS = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "20"))

MODELS = ["8R 410", "7R 330", "6M 155", "9RX 640", "5E 75"]
PARTS = {
    "engine_overheat": {"part": "Cooling package / thermostat kit", "sku": "JD-COOL-4820"},
    "oil_pressure_low": {"part": "Oil filter + pressure sensor", "sku": "JD-OIL-9912"},
    "hydraulic_pressure_drop": {"part": "Hydraulic filter + hose kit", "sku": "JD-HYD-4431"},
    "vibration_high": {"part": "Bearing and mount inspection kit", "sku": "JD-BRG-2240"},
    "battery_low": {"part": "Heavy-duty battery", "sku": "JD-BAT-7710"},
    "dpf_saturation": {"part": "DPF service kit", "sku": "JD-DPF-1500"},
}
FAULT_RULES = [
    {
        "code": "engine_overheat",
        "title": "Engine temperature rising",
        "metric": "engine_temp",
        "threshold": 105,
        "direction": "above",
        "detail": "Cooling system may overheat",
        "weight": 5,
    },
    {
        "code": "oil_pressure_low",
        "title": "Oil pressure falling",
        "metric": "oil_pressure",
        "threshold": 34,
        "direction": "below",
        "detail": "Lubrication risk",
        "weight": 5,
    },
    {
        "code": "hydraulic_pressure_drop",
        "title": "Hydraulic pressure dropping",
        "metric": "hydraulic_pressure",
        "threshold": 2600,
        "direction": "below",
        "detail": "Hydraulic performance loss",
        "weight": 4,
    },
    {
        "code": "vibration_high",
        "title": "Abnormal vibration",
        "metric": "vibration",
        "threshold": 4.8,
        "direction": "above",
        "detail": "Bearing, belt, or mount wear",
        "weight": 4,
    },
    {
        "code": "battery_low",
        "title": "Battery voltage weakening",
        "metric": "battery_voltage",
        "threshold": 11.9,
        "direction": "below",
        "detail": "Starting/charging risk",
        "weight": 3,
    },
    {
        "code": "dpf_saturation",
        "title": "DPF load increasing",
        "metric": "dpf_load",
        "threshold": 85,
        "direction": "above",
        "detail": "Regeneration/service may be needed",
        "weight": 3,
    },
]

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
ws_clients: list[object] = []
ws_clients_lock = threading.Lock()


def build_ws_frame(text: str) -> bytes:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127)
        header.extend(struct.pack("!Q", length))
    return bytes(header) + payload


def broadcast_analysis_update() -> None:
    message = json.dumps({"type": "analysis", "data": get_analysis()})
    frame = build_ws_frame(message)
    with ws_clients_lock:
        clients = list(ws_clients)
    for client in clients:
        try:
            client.sendall(frame)
        except OSError:
            with ws_clients_lock:
                if client in ws_clients:
                    ws_clients.remove(client)


class WebSocketHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        try:
            data = self.request.recv(2048).decode("utf-8", errors="ignore")
        except OSError:
            return

        if "Sec-WebSocket-Key:" not in data:
            return

        key = next(
            (line.split(":", 1)[1].strip() for line in data.splitlines() if line.startswith("Sec-WebSocket-Key:")),
            None,
        )

        if not key:
            return

        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
        )
        self.request.sendall(response.encode("ascii"))

        with ws_clients_lock:
            ws_clients.append(self.request)

        try:
            while True:
                header = self.request.recv(2)
                if not header or len(header) < 2:
                    break
                fin_and_opcode, mask_and_len = header
                opcode = fin_and_opcode & 0x0F
                length = mask_and_len & 0x7F
                if length == 126:
                    ext = self.request.recv(2)
                    length = struct.unpack("!H", ext)[0]
                elif length == 127:
                    ext = self.request.recv(8)
                    length = struct.unpack("!Q", ext)[0]
                mask = self.request.recv(4) if (mask_and_len & 0x80) else None
                if length:
                    self.request.recv(length)
                if opcode == 0x8:
                    break
        finally:
            with ws_clients_lock:
                if self.request in ws_clients:
                    ws_clients.remove(self.request)


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
    if not rows:
        latest = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "engine_temp": 85.0,
            "oil_pressure": 48.0,
            "hydraulic_pressure": 3020.0,
            "vibration": 2.1,
            "battery_voltage": 12.9,
            "dpf_load": 34.0,
            "fuel_rate": 8.0,
        }
        last24 = [latest]
    else:
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
    alerts = []
    tendencies = []
    cycle_count = sum(1 for r in rows if r["fuel_rate"] > 12.5)
    for rule in FAULT_RULES:
        code = rule["code"]
        title = rule["title"]
        metric = rule["metric"]
        threshold = rule["threshold"]
        direction = rule["direction"]
        detail = rule["detail"]
        weight = rule["weight"]
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
    tendencies.extend([
        {"metric": "usage_hours", "current": machine["hours"], "trend24h": 0, "direction": "stable"},
        {"metric": "cycles", "current": cycle_count, "trend24h": 0, "direction": "stable"},
    ])
    risk_score = min(100, round(sum({"critical": 32, "warning": 20, "watch": 10}.get(a["severity"], 0) for a in alerts) + machine["hours"] / 180))
    status = "critical" if any(a["severity"] == "critical" for a in alerts) else "warning" if alerts else "healthy"
    return {"machine": dict(machine), "latest": dict(latest), "alerts": alerts, "tendencies": tendencies, "riskScore": risk_score, "status": status, "usage_hours": machine["hours"], "cycles": cycle_count}


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


def row_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    return [dict(row) for row in rows]


def get_database_context() -> dict:
    """Build the complete data snapshot Gemini receives with field meanings."""
    with connect() as conn:
        machines = row_dicts(conn.execute("SELECT * FROM machines ORDER BY id").fetchall())
        readings = row_dicts(conn.execute("SELECT * FROM readings ORDER BY ts, id").fetchall())
        parts_preparations = row_dicts(
            conn.execute("SELECT * FROM parts_preparations ORDER BY created_at, id").fetchall()
        )

    return {
        "application": "DeereMagic predictive maintenance dashboard for tractor dealer support",
        "databaseFile": DB_PATH.name,
        "snapshotGeneratedAt": datetime.now().isoformat(timespec="seconds"),
        "dataDictionary": {
            "machines": {
                "meaning": "One row per monitored tractor/customer machine.",
                "columns": {
                    "id": "Unique tractor identifier used by all telemetry and alerts.",
                    "model": "Tractor model name.",
                    "customer": "Customer that owns or operates the tractor.",
                    "dealer_region": "Dealer service region responsible for the machine.",
                    "hours": "Total machine operating hours.",
                },
            },
            "readings": {
                "meaning": "Timestamped sensor telemetry rows. Each row belongs to one machine_id.",
                "columns": {
                    "id": "Unique telemetry row id.",
                    "machine_id": "Foreign key to machines.id.",
                    "ts": "ISO timestamp for when this reading was recorded.",
                    "engine_temp": "Engine temperature in Celsius. High values indicate overheating risk.",
                    "oil_pressure": "Oil pressure reading. Low values indicate lubrication risk.",
                    "hydraulic_pressure": "Hydraulic pressure reading. Low values indicate hydraulic system risk.",
                    "vibration": "Vibration level. High values can indicate bearing, belt, or mount wear.",
                    "battery_voltage": "Battery voltage. Low values indicate starting or charging risk.",
                    "dpf_load": "Diesel particulate filter load percentage. High values indicate service/regeneration risk.",
                    "fuel_rate": "Fuel use rate. Values above 12.5 are counted as active work cycles.",
                },
            },
            "parts_preparations": {
                "meaning": "Dealer actions already taken to prepare a part for a predicted or current fault.",
                "columns": {
                    "id": "Unique preparation row id.",
                    "machine_id": "Machine the prepared part is intended for.",
                    "sku": "Dealer stock keeping unit for the part.",
                    "part": "Prepared part name.",
                    "reason": "Alert or service reason for preparing the part.",
                    "status": "Preparation workflow status.",
                    "created_at": "ISO timestamp when the part was prepared.",
                },
            },
            "derivedFaultData": {
                "meaning": "Computed from all machines/readings by the backend analysis model.",
                "fields": {
                    "alerts": "Current and predictive faults sorted by severity.",
                    "fleet": "Per-machine latest telemetry, trends, alerts, risk score, status, usage hours, and cycles.",
                    "dealer.summary": "Fleet-level counts of critical, predictive, and healthy machines.",
                    "dealer.partsForecast": "Recommended part quantities grouped by SKU based on active alerts.",
                    "dealer.usageByRegion": "Machine count, operating hours, and average risk by dealer region.",
                    "hoursToThreshold": "Estimated hours until a metric crosses its fault threshold; 0 means the fault is active now.",
                    "confidence": "Heuristic confidence score from 0 to 1.",
                    "riskScore": "0 to 100 machine risk score built from alert severity and machine hours.",
                },
            },
        },
        "faultLogic": {
            "severityDefinitions": {
                "critical": "The latest metric has already crossed its threshold.",
                "warning": "The trend predicts threshold crossing within 36 hours.",
                "watch": "The trend predicts threshold crossing within 72 hours.",
                "healthy": "No active or predictive alert was detected for the machine.",
            },
            "rules": [
                {**rule, "recommendedPart": PARTS[rule["code"]]["part"], "sku": PARTS[rule["code"]]["sku"]}
                for rule in FAULT_RULES
            ],
        },
        "storedData": {
            "machines": {"rowCount": len(machines), "rows": machines},
            "readings": {"rowCount": len(readings), "rows": readings},
            "parts_preparations": {"rowCount": len(parts_preparations), "rows": parts_preparations},
        },
        "derivedFaultData": get_analysis(),
    }


def build_gemini_prompt(question: str) -> str:
    context = get_database_context()
    context_json = json.dumps(context, ensure_ascii=False, indent=2)
    return (
        "Use the complete DeereMagic tractor maintenance context below to answer the dealer question.\n"
        "The JSON includes a data dictionary explaining what every table, column, fault rule, alert, "
        "risk score, and stored row means. Treat storedData as the raw contents of tractor_sensors.db "
        "and derivedFaultData as the backend fault analysis computed from those rows.\n"
        "Return a text only response, do not use formating.\n\n"
        "Complete context JSON:\n"
        f"{context_json}\n\n"
        "Dealer question:\n"
        f"{question}"
    )


def extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError("Gemini returned an empty response")
    return text


def gemini_chat_reply(question: str) -> str:
    api_key = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY")

    model_name = GEMINI_MODEL[7:] if GEMINI_MODEL.startswith("models/") else GEMINI_MODEL
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": (
                        "You are the DeereMagic dealer assistant. Answer in Spanish unless the user asks "
                        "for another language. Use only the supplied tractor database and fault-analysis "
                        "context. Be concise, cite machine ids and SKUs when relevant, and explain the "
                        "meaning of sensor values or faults in plain dealer-service terms."
                    )
                }
            ]
        },
        "contents": [{"role": "user", "parts": [{"text": build_gemini_prompt(question)}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=GEMINI_TIMEOUT_SECONDS) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gemini API returned HTTP {exc.code}: {body[:300]}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

    return extract_gemini_text(response_payload)


def normalize_query(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def keyword_help_text() -> str:
    return "Prueba palabras clave: 'resumen', 'alertas recientes', 'repuestos', 'maquinas', 'riesgo', 'ultimos eventos'."


def label_metric(metric: str) -> str:
    labels = {
        "engine_temp": "temperatura del motor",
        "oil_pressure": "presion de aceite",
        "hydraulic_pressure": "presion hidraulica",
        "vibration": "vibracion",
        "battery_voltage": "voltaje de bateria",
        "dpf_load": "carga del DPF",
        "usage_hours": "horas de uso",
        "cycles": "ciclos de trabajo",
    }
    return labels.get(metric, metric.replace("_", " "))


def keyword_chat_reply(question: str) -> str:
    analysis_data = get_analysis()
    q = normalize_query(question)

    if "resumen" in q or "summary" in q or "important" in q:
        s = analysis_data["dealer"]["summary"]
        return (
            f"Resumen: {s['machines']} maquinas - Criticos: {s['critical']}, "
            f"Predictivos: {s['predictive']}, Saludables: {s['healthy']}. "
            f"Generado: {analysis_data['generatedAt']}"
        )

    if "alert" in q or "reciente" in q or "recent" in q or "evento" in q or "event" in q or "ultimo" in q:
        alerts = analysis_data["alerts"][:5]
        if not alerts:
            return "No hay alertas recientes."
        return "\n".join(
            f"{a['machineId']}: {a['title']} ({a['severity']}) - {a['detail']}. "
            f"{label_metric(a['metric'])}: {a['current']} / umbral {a['threshold']}"
            for a in alerts
        )

    if "repuesto" in q or "parts" in q or "sku" in q:
        parts = analysis_data["dealer"]["partsForecast"][:5]
        if not parts:
            return "No hay repuestos sugeridos ahora."
        return "\n".join(f"{p['part']} (SKU {p['sku']}) - Cantidad {p['quantity']}" for p in parts)

    if "maquina" in q or "machine" in q or "fleet" in q or "flota" in q:
        return f"Maquinas monitorizadas: {analysis_data['dealer']['summary']['machines']}"

    if "riesgo" in q or "risk" in q or "top risk" in q:
        top = sorted(analysis_data["fleet"], key=lambda item: item["riskScore"], reverse=True)[:3]
        if not top:
            return "Sin datos de riesgo."
        return "\n".join(
            f"{item['machine']['id']} - {item['machine']['customer']} - Riesgo {item['riskScore']}"
            for item in top
        )

    return "No he entendido. " + keyword_help_text()


def answer_chat_message(body: dict) -> tuple[dict, int]:
    question = str(body.get("message") or body.get("question") or "").strip()
    if not question:
        return {"error": "Missing message"}, 400

    try:
        return {"reply": gemini_chat_reply(question), "source": "gemini", "model": GEMINI_MODEL}, 200
    except Exception as exc:
        return {
            "reply": keyword_chat_reply(question),
            "source": "keyword-fallback",
            "model": "keyword",
            "fallbackReason": str(exc),
        }, 200


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
    broadcast_analysis_update()
    return {
        "ok": True,
        "message": f"Telemetry accepted for {machine_id}",
        "machine": analyzed,
        "alerts": analyzed["alerts"],
    }, 201


def clear_db() -> dict:
    with connect() as conn:
        conn.executescript(
            """
            DELETE FROM parts_preparations;
            DELETE FROM readings;
            """
        )
    broadcast_analysis_update()
    return {"ok": True, "message": "All telemetry and demo preparation history has been cleared."}


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

        if parsed.path == "/api/chat":
            data, status = answer_chat_message(body)
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
            broadcast_analysis_update()
            return self._json({"ok": True, "message": f"Prepared {body['part']} for {body['machineId']}"})

        if parsed.path == "/api/clear-db":
            return self._json(clear_db())

        return self._json({"error": "Not found"}, 404)

    def log_message(self, format, *args):
        print("%s - %s" % (self.address_string(), format % args))


class ThreadedWebSocketServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8000"))
    ws_port = int(os.environ.get("WS_PORT", "8001"))
    host = "0.0.0.0"
    print(f"Serving predictive maintenance dashboard on http://{host}:{port}")
    print(f"Broadcasting live updates on ws://{host}:{ws_port}/ws")
    print("Access this from other devices using your machine's IP address on the same network.")

    ws_server = ThreadedWebSocketServer((host, ws_port), WebSocketHandler)
    threading.Thread(target=ws_server.serve_forever, daemon=True).start()

    ThreadingHTTPServer((host, port), Handler).serve_forever()
