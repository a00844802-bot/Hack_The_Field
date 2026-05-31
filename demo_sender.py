#!/usr/bin/env python3
"""Send demo telemetry to the tractor predictive maintenance backend.

Examples:
  python demo_sender.py --server http://localhost:8000 --machine JD-8R-1001 --preset overheat
  python demo_sender.py --server http://192.168.1.20:8000 --machine JD-8R-1001 --preset oil
"""
import argparse
import json
import urllib.request

PRESETS = {
    "normal": {"engine_temp": 92, "oil_pressure": 44, "hydraulic_pressure": 2950, "vibration": 2.8, "battery_voltage": 12.6, "dpf_load": 52, "fuel_rate": 15},
    "overheat": {"engine_temp": 113, "oil_pressure": 41, "hydraulic_pressure": 2920, "vibration": 3.1, "battery_voltage": 12.5, "dpf_load": 58, "fuel_rate": 18},
    "oil": {"engine_temp": 96, "oil_pressure": 29, "hydraulic_pressure": 2910, "vibration": 3.0, "battery_voltage": 12.5, "dpf_load": 60, "fuel_rate": 17},
    "hydraulic": {"engine_temp": 94, "oil_pressure": 42, "hydraulic_pressure": 2420, "vibration": 3.4, "battery_voltage": 12.4, "dpf_load": 57, "fuel_rate": 16},
    "vibration": {"engine_temp": 95, "oil_pressure": 40, "hydraulic_pressure": 2890, "vibration": 5.6, "battery_voltage": 12.4, "dpf_load": 59, "fuel_rate": 16},
    "battery": {"engine_temp": 92, "oil_pressure": 42, "hydraulic_pressure": 2920, "vibration": 3.0, "battery_voltage": 11.5, "dpf_load": 55, "fuel_rate": 15},
    "dpf": {"engine_temp": 98, "oil_pressure": 42, "hydraulic_pressure": 2910, "vibration": 3.0, "battery_voltage": 12.4, "dpf_load": 91, "fuel_rate": 18},
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://localhost:8000")
    parser.add_argument("--machine", required=True, help="Machine ID shown in the dashboard, for example JD-8R-1001")
    parser.add_argument("--preset", choices=PRESETS, default="normal")
    args = parser.parse_args()

    payload = {"machineId": args.machine, **PRESETS[args.preset]}
    req = urllib.request.Request(
        args.server.rstrip("/") + "/api/readings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as res:
        print(res.read().decode("utf-8"))

if __name__ == "__main__":
    main()
