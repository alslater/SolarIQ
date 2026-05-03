"""Seed Solcast forecast data into InfluxDB from a JSON file or stdin.

Usage:
    uv run python -m solariq.scripts.seed_solcast forecast.json
    echo '{"date": "2026-05-03", "slots": [...]}' | uv run python -m solariq.scripts.seed_solcast

JSON format: {"date": "YYYY-MM-DD", "slots": [48 floats in kWh]}
"""

import json
import sys
from datetime import date


def main() -> None:
    if len(sys.argv) > 1:
        path = sys.argv[1]
        try:
            with open(path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            print(f"Error reading {path}: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as exc:
            print(f"Error parsing JSON from stdin: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        for_date = date.fromisoformat(data["date"])
        slots = data["slots"]
    except (KeyError, ValueError) as exc:
        print(f"Invalid JSON structure: {exc}", file=sys.stderr)
        sys.exit(1)

    if len(slots) != 48:
        print(f"Expected 48 slots, got {len(slots)}", file=sys.stderr)
        sys.exit(1)

    from solariq.config import load_config
    from solariq.data.influx import save_solar_forecast_influx

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        save_solar_forecast_influx(config, slots, for_date)
        total = sum(slots)
        print(
            f"Seeded {len(slots)} slots for {for_date} "
            f"(total {total:.3f} kWh) into InfluxDB database "
            f"'{config.influxdb.solcast_forecast_database}'"
        )
    except Exception as exc:
        print(f"Failed to write to InfluxDB: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
