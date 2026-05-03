import reflex as rx
from solariq.ui.state import AppState
from solariq.ui.components import stat_card
from solariq.ui import theme as t

_INTERVALS = [5, 10, 30, 60, 300]
_INTERVAL_LABELS = {5: "5s", 10: "10s", 30: "30s", 60: "60s", 300: "5m"}


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


def _interval_btn(seconds: int, label: str) -> rx.Component:
    is_active = AppState.inverter_refresh_interval == seconds
    return rx.button(
        label,
        on_click=AppState.set_inverter_refresh_interval(seconds),
        style={
            "background": rx.cond(is_active, t.PRIMARY, "transparent"),
            "color": rx.cond(is_active, "#060a12", t.MUTED),
            "border": rx.cond(is_active, f"1px solid {t.PRIMARY}", f"1px solid {t.BORDER}"),
            "border_radius": "4px",
            "padding": "4px 10px",
            "font_size": "12px",
            "font_weight": "600",
            "cursor": "pointer",
            "font_family": "Inter, system-ui, sans-serif",
        },
    )


def inverter_tab() -> rx.Component:
    return rx.vstack(
        # Header row: title + last reading
        rx.hstack(
            rx.vstack(
                rx.heading(
                    "Inverter Stats",
                    style={"font_size": "18px", "font_weight": "700", "color": t.FG},
                ),
                rx.cond(
                    AppState.inverter_recorded_at != "",
                    rx.text(
                        f"Last reading: {AppState.inverter_recorded_at}",
                        style={"font_size": "12px", "color": t.MUTED},
                    ),
                    rx.fragment(),
                ),
                spacing="1",
                align="start",
            ),
            rx.spacer(),
            # Interval selector + manual refresh
            rx.hstack(
                rx.text("Refresh:", style={"font_size": "12px", "color": t.MUTED, "align_self": "center"}),
                *[_interval_btn(s, _INTERVAL_LABELS[s]) for s in _INTERVALS],
                rx.button(
                    rx.cond(
                        AppState.inverter_loading,
                        rx.icon("loader-circle", size=14),
                        rx.icon("refresh-cw", size=14),
                    ),
                    on_click=AppState.load_inverter_stats,
                    disabled=AppState.inverter_loading,
                    title="Refresh now",
                    style={
                        "background": "#0d2b3e",
                        "border": f"1px solid {t.PRIMARY}",
                        "color": t.PRIMARY,
                        "border_radius": "6px",
                        "padding": "6px 10px",
                        "cursor": "pointer",
                        "_hover": {"background": "#0a3a52"},
                    },
                ),
                spacing="2",
                align="center",
            ),
            width="100%",
            align="center",
            margin_bottom="12px",
        ),
        # Countdown progress bar (only for intervals >= 30s)
        rx.cond(
            AppState.inverter_refresh_interval >= 30,
        rx.hstack(
            rx.box(
                rx.box(
                    style={
                        "height": "100%",
                        "width": f"{AppState.inverter_refresh_progress}%",
                        "background": t.PRIMARY,
                        "border_radius": "2px",
                        "transition": "width 0.9s linear",
                    },
                ),
                style={
                    "flex": "1",
                    "height": "4px",
                    "background": t.BORDER,
                    "border_radius": "2px",
                    "overflow": "hidden",
                },
            ),
            rx.text(
                f"{AppState.inverter_countdown}s",
                style={"font_size": "11px", "color": t.MUTED, "min_width": "28px", "text_align": "right"},
            ),
            spacing="3",
            align="center",
            width="100%",
            margin_bottom="16px",
        ),
        ),
        # Error message
        rx.cond(
            AppState.inverter_error != "",
            rx.box(
                rx.text(AppState.inverter_error, style={"font_size": "13px", "color": t.FAIL}),
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
        # Power flows section
        rx.box(
            _section_heading("Power Flows (kW)"),
            rx.hstack(
                stat_card("Solar", rx.text(f"{AppState.inverter_pvpower_kw} kW")),
                stat_card("Grid Import", rx.text(f"{AppState.inverter_power_in_kw} kW")),
                stat_card("Grid Export", rx.text(f"{AppState.inverter_power_out_kw} kW")),
                stat_card(
                    "Feed-in Net",
                    rx.text(
                        f"{AppState.inverter_feedin_kw} kW",
                        color=rx.cond(
                            AppState.inverter_feedin_kw > 0,
                            t.PASS,
                            rx.cond(AppState.inverter_feedin_kw < 0, t.FAIL, t.FG),
                        ),
                    ),
                    rx.cond(AppState.inverter_feedin_kw > 0, "Exporting", rx.cond(AppState.inverter_feedin_kw < 0, "Importing", "")),
                ),
                stat_card(
                    "Battery",
                    rx.text(
                        f"{AppState.inverter_battery_power_kw} kW",
                        color=rx.cond(
                            AppState.inverter_battery_power_kw > 0,
                            t.PASS,
                            rx.cond(AppState.inverter_battery_power_kw < 0, t.FAIL, t.FG),
                        ),
                    ),
                    rx.cond(AppState.inverter_battery_power_kw > 0, "Charging", rx.cond(AppState.inverter_battery_power_kw < 0, "Discharging", "")),
                ),
                stat_card("Home Usage", rx.text(f"{AppState.inverter_usage_kw} kW")),
                spacing="3",
                wrap="wrap",
            ),
            style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "16px", "width": "100%"},
        ),
        # Battery & system section
        rx.box(
            _section_heading("Battery & System"),
            rx.hstack(
                stat_card("Battery SOC", rx.text(f"{AppState.inverter_soc_pct}%")),
                stat_card("Battery Temp", rx.text(f"{AppState.inverter_battery_temp_c} °C")),
                stat_card("Inverter Temp", rx.text(f"{AppState.inverter_temp_c} °C")),
                stat_card(
                    "Grid Voltage",
                    rx.text(
                        f"{AppState.inverter_grid_voltage_v} V",
                        color=rx.cond(
                            (AppState.inverter_grid_voltage_v < 216.2) | (AppState.inverter_grid_voltage_v > 253.0),
                            t.FAIL,
                            t.FG,
                        ),
                    ),
                    rx.cond(
                        (AppState.inverter_grid_voltage_v < 216.2) | (AppState.inverter_grid_voltage_v > 253.0),
                        "Outside UK range (216.2–253 V)",
                        "UK range: 216.2–253 V",
                    ),
                ),
                spacing="3",
                wrap="wrap",
            ),
            style={**t.CARD_STYLE, "padding": "20px", "width": "100%"},
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
        on_mount=AppState.start_inverter_polling,
    )
