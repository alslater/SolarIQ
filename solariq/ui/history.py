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


def _date_input(label: str, value: rx.Var, on_change) -> rx.Component:
    return rx.box(
        rx.text(
            label,
            style={
                "font_size": "11px",
                "font_weight": "500",
                "color": t.MUTED,
                "text_transform": "uppercase",
                "letter_spacing": "0.06em",
                "margin_bottom": "6px",
            },
        ),
        rx.input(
            type="date",
            value=value,
            on_change=on_change,
            style={
                "background": t.SECONDARY,
                "border": f"1px solid {t.BORDER}",
                "border_radius": "6px",
                "color": t.FG,
                "font_family": "Inter, system-ui, sans-serif",
                "font_size": "14px",
                "padding": "8px 12px",
                "cursor": "pointer",
                "_focus": {"outline": f"2px solid {t.PRIMARY}", "border_color": t.PRIMARY},
            },
        ),
    )


def _quick_btn(label: str, on_click) -> rx.Component:
    return rx.button(
        label,
        on_click=on_click,
        style={
            "background": t.SECONDARY,
            "color": t.MUTED,
            "border": f"1px solid {t.BORDER}",
            "border_radius": "6px",
            "padding": "5px 12px",
            "font_size": "12px",
            "font_weight": "500",
            "cursor": "pointer",
            "font_family": "Inter, system-ui, sans-serif",
            "_hover": {"background": t.CARD_ALT, "color": t.FG, "border_color": t.PRIMARY},
        },
    )


def history_tab() -> rx.Component:
    return rx.vstack(
        # Date range selector
        rx.box(
            _section_heading("Select Date Range"),
            rx.hstack(
                _quick_btn("Yesterday", AppState.select_yesterday),
                _quick_btn("Day before yesterday", AppState.select_day_before_yesterday),
                _quick_btn("This week", AppState.select_this_week),
                _quick_btn("Last week", AppState.select_last_week),
                spacing="2",
                margin_bottom="12px",
                wrap="wrap",
            ),
            rx.hstack(
                _date_input("From", AppState.history_start_date, AppState.set_history_start),
                _date_input("To", AppState.history_end_date, AppState.set_history_end),
                rx.box(
                    rx.button(
                        "Load",
                        on_click=AppState.load_history,
                        loading=AppState.history_loading,
                        style={
                            "background": t.PRIMARY,
                            "color": "#060a12",
                            "border": "none",
                            "border_radius": "6px",
                            "padding": "8px 20px",
                            "font_size": "14px",
                            "font_weight": "600",
                            "cursor": "pointer",
                            "font_family": "Inter, system-ui, sans-serif",
                            "align_self": "flex-end",
                            "_hover": {"background": t.ACCENT},
                        },
                    ),
                    style={"display": "flex", "align_items": "flex-end"},
                ),
                spacing="4",
                align="end",
                wrap="wrap",
            ),
            style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
        ),
        # Error
        rx.cond(
            AppState.history_error != "",
            rx.box(
                rx.text(AppState.history_error, style={"font_size": "13px", "color": t.FAIL}),
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
        # Summary stats and charts — shown only when data is loaded
        rx.cond(
            AppState.history_has_data,
            rx.vstack(
                rx.hstack(
                    stat_card("Solar", rx.text(f"{AppState.history_solar_kwh} kWh")),
                    stat_card("Grid Import", rx.text(f"{AppState.history_grid_import_kwh} kWh")),
                    stat_card("Grid Export", rx.text(f"{AppState.history_grid_export_kwh} kWh")),
                    stat_card("Grid Cost", rx.text(AppState.history_grid_cost_str)),
                    stat_card("Export Revenue", rx.text(AppState.history_grid_export_revenue_str)),
                    stat_card("Solar Saving", rx.text(AppState.history_solar_saving_str)),
                    stat_card("Battery Peak Saving", rx.text(AppState.history_battery_peak_saving_str)),
                    stat_card("Net Period Cost", rx.text(AppState.history_net_period_cost_str), "incl. standing charge"),
                    spacing="3",
                    wrap="wrap",
                    margin_bottom="6",
                ),
                # Solar, grid import & export chart
                rx.box(
                    _section_heading("Solar, Grid Import & Export (kWh)"),
                    rx.recharts.bar_chart(
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                        rx.recharts.bar(
                            data_key="solar_kwh",
                            name="Solar",
                            fill=t.CHART_SOLAR,
                            fill_opacity=0.7,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.recharts.bar(
                            data_key="grid_import_kwh",
                            name="Grid Import",
                            fill=t.CHART_IMPORT,
                            fill_opacity=0.7,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.recharts.bar(
                            data_key="grid_export_kwh",
                            name="Grid Export",
                            fill=t.CHART_EXPORT,
                            fill_opacity=0.7,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.recharts.x_axis(
                            data_key="date",
                            tick={"fill": t.CHART_MUTED, "fontSize": 10},
                            interval="preserveStartEnd",
                        ),
                        rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                        rx.recharts.legend(),
                        rx.recharts.tooltip(),
                        data=AppState.history_chart_data,
                        width="100%",
                        height=300,
                        bar_size=20,
                        bar_gap=-20,
                    ),
                    style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
                ),
                # Solar actual vs predicted chart
                rx.box(
                    _section_heading("Solar: Actual vs Predicted PV (kWh)"),
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
                    rx.recharts.composed_chart(
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                        rx.recharts.bar(
                            data_key="solar_kwh",
                            name="Actual Solar",
                            fill=t.CHART_SOLAR,
                            fill_opacity=0.8,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.cond(
                            AppState.today_show_solcast_forecast,
                            rx.recharts.line(
                                data_key="predicted_solar_solcast_kwh",
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
                                data_key="predicted_solar_forecast_solar_kwh",
                                name="forecast.solar Forecast",
                                stroke="#22c55e",
                                stroke_width=2,
                                dot=False,
                                stroke_dasharray="6 3",
                            ),
                            rx.fragment(),
                        ),
                        rx.recharts.x_axis(
                            data_key="date",
                            tick={"fill": t.CHART_MUTED, "fontSize": 10},
                            interval="preserveStartEnd",
                        ),
                        rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                        rx.recharts.legend(),
                        rx.recharts.tooltip(),
                        data=AppState.history_chart_data,
                        width="100%",
                        height=240,
                        bar_size=20,
                    ),
                    style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
                ),
                # Grid cost vs export revenue chart
                rx.box(
                    _section_heading("Grid Cost vs Export Revenue (£)"),
                    rx.recharts.bar_chart(
                        rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                        rx.recharts.bar(
                            data_key="grid_cost_gbp",
                            name="Grid Cost £",
                            fill=t.CHART_IMPORT,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.recharts.bar(
                            data_key="grid_export_revenue_gbp",
                            name="Export Revenue £",
                            fill=t.CHART_EXPORT,
                            radius=[2, 2, 0, 0],
                        ),
                        rx.recharts.x_axis(
                            data_key="date",
                            tick={"fill": t.CHART_MUTED, "fontSize": 10},
                            interval="preserveStartEnd",
                        ),
                        rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                        rx.recharts.legend(),
                        rx.recharts.tooltip(),
                        data=AppState.history_chart_data,
                        width="100%",
                        height=220,
                        bar_category_gap="20%",
                    ),
                    style={**t.CARD_STYLE, "padding": "20px", "width": "100%"},
                ),
                width="100%",
            ),
            rx.fragment(),
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
    )
