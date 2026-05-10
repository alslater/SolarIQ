"""Compare Solcast and forecast.solar forecasts against actual PV generation.

Usage:
    uv run python -m solariq.scripts.compare_forecasts
    uv run python -m solariq.scripts.compare_forecasts --days 14
    uv run python -m solariq.scripts.compare_forecasts --start 2026-04-01 --end 2026-04-30
    uv run python -m solariq.scripts.compare_forecasts --detail
    uv run python -m solariq.scripts.compare_forecasts --excel report.xlsx
    uv run python -m solariq.scripts.compare_forecasts --excel report.xlsx --quiet
"""

import argparse
import sys
from datetime import date, timedelta


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Compare the last N complete days (default: 7).",
    )
    date_group.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="Range start date (requires --end).",
    )
    parser.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="Range end date, inclusive (requires --start).",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Print per-slot breakdown for each day in the terminal output.",
    )
    parser.add_argument(
        "--excel",
        metavar="PATH",
        help="Write .xlsx file with Summary and Detail worksheets.",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress terminal output (warnings still go to stderr).",
    )
    args = parser.parse_args()

    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be used together.")
    if args.start and args.days != 7:
        parser.error("--days cannot be used with --start/--end.")

    return args


def _resolve_dates(args: argparse.Namespace) -> tuple[date, date]:
    if args.start:
        try:
            start = date.fromisoformat(args.start)
            end = date.fromisoformat(args.end)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        if end < start:
            print("ERROR: --end must be on or after --start", file=sys.stderr)
            sys.exit(1)
        return start, end
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    return start, end


def _slot_time(slot: int) -> str:
    h, m = divmod(slot * 30, 60)
    return f"{h:02d}:{m:02d}"


def _print_terminal(results: list, detail: bool) -> None:
    from tabulate import tabulate

    summary_rows = []
    for r in results:
        mae_winner = "SC" if r.solcast_mae <= r.forecast_solar_mae else "FS"
        rmse_winner = "SC" if r.solcast_rmse <= r.forecast_solar_rmse else "FS"
        summary_rows.append([
            r.date.isoformat(),
            f"{sum(r.actual_slots):.2f}",
            f"{sum(r.solcast_slots):.2f}",
            f"{r.solcast_mae:.4f}",
            f"{r.solcast_rmse:.4f}",
            f"{sum(r.forecast_solar_slots):.2f}",
            f"{r.forecast_solar_mae:.4f}",
            f"{r.forecast_solar_rmse:.4f}",
            f"{mae_winner}/{rmse_winner}",
        ])

    headers = [
        "Date", "Actual kWh",
        "SC kWh", "SC MAE", "SC RMSE",
        "FS kWh", "FS MAE", "FS RMSE",
        "Winner MAE/RMSE",
    ]
    print(tabulate(summary_rows, headers=headers, tablefmt="simple"))

    overall_actual = sum(sum(r.actual_slots) for r in results)
    overall_sc_kwh = sum(sum(r.solcast_slots) for r in results)
    overall_fs_kwh = sum(sum(r.forecast_solar_slots) for r in results)
    overall_sc_mae = sum(r.solcast_mae for r in results) / len(results)
    overall_sc_rmse = sum(r.solcast_rmse for r in results) / len(results)
    overall_fs_mae = sum(r.forecast_solar_mae for r in results) / len(results)
    overall_fs_rmse = sum(r.forecast_solar_rmse for r in results) / len(results)

    print("-" * 80)
    print(
        f"{'Overall':<12} {overall_actual:>10.2f}"
        f" {overall_sc_kwh:>8.2f} {overall_sc_mae:>8.4f} {overall_sc_rmse:>9.4f}"
        f" {overall_fs_kwh:>8.2f} {overall_fs_mae:>8.4f} {overall_fs_rmse:>9.4f}"
    )

    mae_winner = "Solcast" if overall_sc_mae <= overall_fs_mae else "forecast.solar"
    rmse_winner = "Solcast" if overall_sc_rmse <= overall_fs_rmse else "forecast.solar"
    print(f"Winner (MAE):  {mae_winner}")
    print(f"Winner (RMSE): {rmse_winner}")

    if detail:
        for r in results:
            print(f"\n{r.date.isoformat()} slot detail:")
            slot_rows = [
                [
                    i,
                    _slot_time(i),
                    f"{r.actual_slots[i]:.4f}",
                    f"{r.solcast_slots[i]:.4f}",
                    f"{abs(r.solcast_slots[i] - r.actual_slots[i]):.4f}",
                    f"{r.forecast_solar_slots[i]:.4f}",
                    f"{abs(r.forecast_solar_slots[i] - r.actual_slots[i]):.4f}",
                ]
                for i in range(48)
            ]
            print(tabulate(
                slot_rows,
                headers=["Slot", "Time", "Actual", "Solcast", "SC Err", "ForecastSolar", "FS Err"],
                tablefmt="simple",
            ))


def _write_excel(results: list, path: str) -> None:
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()

    ws_summary = wb.active
    ws_summary.title = "Summary"
    summary_headers = [
        "Date", "Actual kWh",
        "SC kWh", "SC MAE", "SC RMSE",
        "FS kWh", "FS MAE", "FS RMSE",
    ]
    ws_summary.append(summary_headers)
    for cell in ws_summary[1]:
        cell.font = Font(bold=True)

    for r in results:
        ws_summary.append([
            r.date.isoformat(),
            round(sum(r.actual_slots), 4),
            round(sum(r.solcast_slots), 4),
            round(r.solcast_mae, 6),
            round(r.solcast_rmse, 6),
            round(sum(r.forecast_solar_slots), 4),
            round(r.forecast_solar_mae, 6),
            round(r.forecast_solar_rmse, 6),
        ])

    n = len(results)
    ws_summary.append([
        "Overall",
        round(sum(sum(r.actual_slots) for r in results), 4),
        round(sum(sum(r.solcast_slots) for r in results), 4),
        round(sum(r.solcast_mae for r in results) / n, 6),
        round(sum(r.solcast_rmse for r in results) / n, 6),
        round(sum(sum(r.forecast_solar_slots) for r in results), 4),
        round(sum(r.forecast_solar_mae for r in results) / n, 6),
        round(sum(r.forecast_solar_rmse for r in results) / n, 6),
    ])

    ws_detail = wb.create_sheet("Detail")
    detail_headers = ["Date", "Slot", "Time", "Actual kWh", "Solcast kWh", "SC Error", "ForecastSolar kWh", "FS Error"]
    ws_detail.append(detail_headers)
    for cell in ws_detail[1]:
        cell.font = Font(bold=True)

    for r in results:
        for i in range(48):
            ws_detail.append([
                r.date.isoformat(),
                i,
                _slot_time(i),
                round(r.actual_slots[i], 6),
                round(r.solcast_slots[i], 6),
                round(abs(r.solcast_slots[i] - r.actual_slots[i]), 6),
                round(r.forecast_solar_slots[i], 6),
                round(abs(r.forecast_solar_slots[i] - r.actual_slots[i]), 6),
            ])

    wb.save(path)


def main() -> None:
    args = _parse_args()
    start, end = _resolve_dates(args)

    from solariq.config import load_config
    from solariq.data.forecast_accuracy import compute_range_accuracy

    config = load_config()
    results = compute_range_accuracy(config, start, end)

    if not results:
        print("ERROR: no valid days found in the requested range.", file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        _print_terminal(results, args.detail)

    if args.excel:
        _write_excel(results, args.excel)
        if not args.quiet:
            print(f"\nExcel report written to: {args.excel}")


if __name__ == "__main__":
    main()
