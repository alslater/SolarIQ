"""Re-fetch today's solar forecast(s) and overwrite the data in InfluxDB.

By default re-acquires whichever sources are enabled in app settings.
Pass --source to target a specific source regardless of settings.
Pass --date to backfill a different day.

Usage:
    uv run python -m solariq.scripts.reacquire_forecast
    uv run python -m solariq.scripts.reacquire_forecast --source solcast
    uv run python -m solariq.scripts.reacquire_forecast --source forecast_solar
    uv run python -m solariq.scripts.reacquire_forecast --date 2026-05-04
    uv run python -m solariq.scripts.reacquire_forecast --source solcast --date 2026-05-04
"""

import argparse
import sys
from datetime import date


VALID_SOURCES = ("solcast", "forecast_solar")


def _fetch_and_save(config, for_date: date, source: str) -> None:
    from solariq.data.influx import save_solar_forecast_influx

    if source == "solcast":
        from solariq.data.solcast import fetch_solar_forecast_with_coverage
        print(f"  Fetching Solcast for {for_date} …")
        slots, covered = fetch_solar_forecast_with_coverage(config, for_date)
    else:
        from solariq.data.forecast_solar import fetch_forecast_solar_with_coverage
        print(f"  Fetching forecast.solar for {for_date} …")
        slots, covered = fetch_forecast_solar_with_coverage(config, for_date)

    print(
        f"  Writing {len(covered)} populated slots, total {sum(slots):.3f} kWh …"
    )
    save_solar_forecast_influx(config, slots, for_date, source=source)
    print(f"  Done — {source} forecast for {for_date} written to InfluxDB.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--source",
        choices=VALID_SOURCES,
        default=None,
        help="Which forecast source to reacquire. Defaults to all enabled sources.",
    )
    parser.add_argument(
        "--date",
        default=None,
        metavar="YYYY-MM-DD",
        help="Date to reacquire (default: today).",
    )
    args = parser.parse_args()

    if args.date:
        try:
            for_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date '{args.date}' — expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        for_date = date.today()

    from solariq.app_settings import get_forecast_settings
    from solariq.config import load_config

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    settings = get_forecast_settings(config.app.auth_db_path)

    sources_to_run: list[str]
    if args.source:
        sources_to_run = [args.source]
    else:
        sources_to_run = []
        if settings.collect_solcast:
            sources_to_run.append("solcast")
        if settings.collect_forecast_solar:
            sources_to_run.append("forecast_solar")

    if not sources_to_run:
        print("No sources enabled in app settings. Use --source to force a specific source.")
        sys.exit(0)

    print(f"Reacquiring forecast(s) for {for_date}: {', '.join(sources_to_run)}")
    errors: list[str] = []
    for source in sources_to_run:
        try:
            _fetch_and_save(config, for_date, source)
        except Exception as exc:
            msg = f"  ERROR [{source}]: {exc}"
            print(msg, file=sys.stderr)
            errors.append(msg)

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
