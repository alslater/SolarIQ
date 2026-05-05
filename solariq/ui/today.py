import reflex as rx
from solariq.ui.state import AppState
from solariq.ui.components import stat_card
from solariq.ui import theme as t


def _section_heading(text: str) -> rx.Component:
    return rx.text(
        text,
        style={
            "font_size": "13px",
            "font_weight": "600",
            "color": t.MUTED,
            "text_transform": "uppercase",
            "letter_spacing": "0.06em",
            "margin_bottom": "10px",
        },
    )


def today_tab() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                AppState.today_loading,
                rx.hstack(
                    rx.spinner(size="1"),
                    rx.text("Refreshing today data...", style={"font_size": "12px", "color": t.MUTED}),
                    spacing="2",
                    align="center",
                ),
                rx.fragment(),
            ),
            rx.spacer(),
            rx.button(
                "Refresh",
                on_click=AppState.refresh_today_now,
                style={
                    "background": "transparent",
                    "color": t.MUTED,
                    "border": f"1px solid {t.BORDER}",
                    "border_radius": "6px",
                    "padding": "6px 12px",
                    "font_size": "12px",
                    "font_weight": "600",
                    "cursor": "pointer",
                    "_hover": {"border_color": t.PRIMARY, "color": t.FG},
                },
            ),
            width="100%",
            align="center",
            margin_bottom="8px",
        ),
        # Error message
        rx.cond(
            AppState.today_error != "",
            rx.box(
                rx.text(AppState.today_error, style={"font_size": "13px", "color": t.FAIL}),
                style={
                    **t.CARD_STYLE,
                    "background": "#1a0a0a",
                    "border_color": t.FAIL,
                    "padding": "12px 16px",
                    "margin_bottom": "16px",
                },
            ),
            rx.fragment(),
        ),
        # Summary bar
        rx.hstack(
            rx.hstack(
                stat_card("Battery SOC", rx.text(f"{AppState.battery_soc_pct}%"), f"{AppState.battery_soc_kwh} kWh"),
                stat_card("Solar Today", rx.text(f"{AppState.solar_today_kwh} kWh")),
                stat_card("Grid Usage", rx.text(f"{AppState.grid_import_today_kwh} kWh")),
                stat_card("Grid Export", rx.text(f"{AppState.corrected_export_today_kwh} kWh"), AppState.calibration_label),
                stat_card("Grid Cost", rx.text(AppState.grid_cost_str)),
                stat_card("Export Revenue", rx.text(AppState.corrected_export_revenue_str), AppState.calibration_label),
                stat_card("Net Daily Cost", rx.text(AppState.corrected_net_daily_cost_str), "incl. standing charge"),
                stat_card(
                    "Current Rate",
                    rx.text(AppState.current_rate_str),
                    AppState.current_export_rate_str,
                ),
                stat_card("Avg Rate", rx.text(AppState.avg_import_rate_str), AppState.avg_export_rate_str),
                stat_card("Avg Paid Rate", rx.text(AppState.avg_paid_rate_str), "weighted by import kWh"),
                spacing="3",
                wrap="wrap",
                flex="1",
            ),
            stat_card(
                "Weather",
                rx.hstack(
                    rx.icon(tag=AppState.today_weather_icon, size=20),
                    rx.text(AppState.today_weather_label),
                    spacing="2",
                    align="center",
                ),
                AppState.today_weather_temp_str,
            ),
            justify="between",
            align="start",
            width="100%",
            margin_bottom="6",
        ),
        # Usage + SOC chart
        rx.box(
            _section_heading("Grid Import, Solar & Export (kWh per 30-min slot)"),
            rx.recharts.composed_chart(
                rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                rx.recharts.bar(data_key="grid_import", name="Grid Import", fill=t.CHART_IMPORT, fill_opacity=0.7, radius=[2, 2, 0, 0]),
                rx.recharts.bar(data_key="solar", name="Solar", fill=t.CHART_SOLAR, fill_opacity=0.7, radius=[2, 2, 0, 0]),
                rx.recharts.bar(data_key="grid_export", name="Grid Export", fill=t.CHART_EXPORT, fill_opacity=0.7, radius=[2, 2, 0, 0]),
                rx.recharts.line(
                    data_key="soc_pct",
                    name="Battery SOC %",
                    stroke="#a78bfa",
                    stroke_width=2,
                    dot=False,
                    y_axis_id="right",
                ),
                rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
                rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                rx.recharts.y_axis(y_axis_id="right", orientation="right", tick={"fill": t.CHART_MUTED, "fontSize": 10}, domain=[0, 100]),
                rx.recharts.legend(),
                rx.recharts.tooltip(),
                data=AppState.today_chart_data,
                width="100%",
                height=250,
                bar_size=20,
                bar_gap=-20,
            ),
            style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
        ),
        # Solar forecast visibility toggles
        rx.hstack(
            rx.text("Forecast Lines:", style={"font_size": "12px", "color": t.MUTED}),
            rx.checkbox(
                checked=AppState.today_show_solcast_forecast,
                on_change=AppState.set_today_show_solcast_forecast,
            ),
            rx.text("Solcast", style={"font_size": "12px", "color": t.FG}),
            rx.checkbox(
                checked=AppState.today_show_forecast_solar_forecast,
                on_change=AppState.set_today_show_forecast_solar_forecast,
            ),
            rx.text("forecast.solar", style={"font_size": "12px", "color": t.FG}),
            spacing="2",
            align="center",
            width="100%",
            margin_bottom="8px",
            wrap="wrap",
        ),
        # Solar actual vs forecast providers
        rx.box(
            _section_heading("Solar: Actual vs Forecast (kWh per slot)"),
            rx.recharts.composed_chart(
                rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                rx.recharts.bar(
                    data_key="solar",
                    name="Actual Solar",
                    fill=t.CHART_SOLAR,
                    fill_opacity=0.8,
                    radius=[2, 2, 0, 0],
                ),
                rx.cond(
                    AppState.today_show_solcast_forecast,
                    rx.recharts.line(
                        data_key="predicted_solar_solcast",
                        name="Solcast Forecast",
                        stroke="#f59e0b",
                        stroke_width=2,
                        dot=False,
                        stroke_dasharray="4 2",
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    AppState.today_show_forecast_solar_forecast,
                    rx.recharts.line(
                        data_key="predicted_solar_forecast_solar",
                        name="forecast.solar Forecast",
                        stroke="#22c55e",
                        stroke_width=2,
                        dot=False,
                        stroke_dasharray="6 3",
                    ),
                    rx.fragment(),
                ),
                rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
                rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                rx.recharts.legend(),
                rx.recharts.tooltip(),
                data=AppState.today_chart_data,
                width="100%",
                height=200,
                bar_size=20,
            ),
            style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
        ),
        # Price chart — import and export rates
        rx.box(
            _section_heading("Today's Agile Rates (p/kWh)"),
            rx.recharts.composed_chart(
                rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                rx.recharts.bar(data_key="import", name="Import Rate", fill=t.CHART_IMPORT, fill_opacity=0.7, radius=[2, 2, 0, 0]),
                rx.recharts.bar(data_key="export", name="Export Rate", fill=t.CHART_EXPORT, fill_opacity=0.7, radius=[2, 2, 0, 0]),
                rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
                rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                rx.recharts.legend(),
                rx.recharts.tooltip(),
                data=AppState.today_price_data,
                width="100%",
                height=200,
                bar_size=20,
                bar_gap=-20,
            ),
            style={**t.CARD_STYLE, "padding": "20px", "width": "100%"},
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
        on_mount=AppState.restart_today_polling,
    )
