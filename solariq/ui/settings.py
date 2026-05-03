import reflex as rx
from solariq.ui.state import AppState
from solariq.ui import theme as t


def settings_tab() -> rx.Component:
    return rx.vstack(
        # Calibration section
        rx.box(
            # Section heading
            rx.text(
                "Export Calibration",
                style={
                    "font_size": "13px",
                    "font_weight": "600",
                    "color": t.MUTED,
                    "text_transform": "uppercase",
                    "letter_spacing": "0.06em",
                    "margin_bottom": "16px",
                },
            ),
            # Uncalibrated warning (shown when no calibration data exists)
            rx.cond(
                (AppState.export_factor == 1.0) & (AppState.calibration_computed_at == ""),
                rx.box(
                    rx.text(
                        "⚠ Uncalibrated — export figures may be inaccurate. Click Recalibrate to fetch correction data.",
                        style={"font_size": "13px", "color": "#f59e0b"},
                    ),
                    style={
                        **t.CARD_STYLE,
                        "background": "#1a1200",
                        "border_color": "#f59e0b",
                        "padding": "12px 16px",
                        "margin_bottom": "16px",
                    },
                ),
                rx.fragment(),
            ),
            # Calibration info (shown when calibration data exists)
            rx.cond(
                AppState.calibration_computed_at != "",
                rx.vstack(
                    rx.text(
                        f"Export correction factor: ×{AppState.export_factor:.3f}",
                        style={"font_size": "14px", "color": t.FG, "font_weight": "500"},
                    ),
                    rx.text(
                        f"Octopus 30-day export: {AppState.calibration_octopus_kwh} kWh  |  InfluxDB: {AppState.calibration_influx_kwh} kWh",
                        style={"font_size": "13px", "color": t.MUTED},
                    ),
                    rx.text(
                        f"Computed: {AppState.calibration_age_str} ({AppState.calibration_computed_at_local})",
                        style={"font_size": "12px", "color": t.MUTED},
                    ),
                    spacing="1",
                    margin_bottom="16px",
                ),
                rx.fragment(),
            ),
            # Error display
            rx.cond(
                AppState.calibration_error != "",
                rx.box(
                    rx.text(AppState.calibration_error, style={"font_size": "13px", "color": t.FAIL}),
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
            # Recalibrate button
            rx.button(
                rx.cond(AppState.calibration_loading, "Recalibrating…", "Recalibrate"),
                on_click=AppState.recalibrate,
                loading=AppState.calibration_loading,
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
                    "_hover": {"background": t.ACCENT},
                },
            ),
            style={**t.CARD_STYLE, "padding": "24px", "width": "100%"},
        ),
        # Cache section
        rx.box(
            rx.text(
                "Cache",
                style={
                    "font_size": "13px",
                    "font_weight": "600",
                    "color": t.MUTED,
                    "text_transform": "uppercase",
                    "letter_spacing": "0.06em",
                    "margin_bottom": "16px",
                },
            ),
            rx.text(
                "Clears today.json, strategy.json, solar_forecast_today.json and calibration.json. "
                "The worker will repopulate them on its next run.",
                style={"font_size": "13px", "color": t.MUTED, "margin_bottom": "16px"},
            ),
            rx.cond(
                AppState.cache_clear_message != "",
                rx.text(
                    AppState.cache_clear_message,
                    style={"font_size": "13px", "color": t.PASS, "margin_bottom": "12px"},
                ),
                rx.fragment(),
            ),
            rx.button(
                "Clear Cache",
                on_click=AppState.clear_cache,
                style={
                    "background": "#1a0a0a",
                    "color": t.FAIL,
                    "border": f"1px solid {t.FAIL}",
                    "border_radius": "6px",
                    "padding": "8px 20px",
                    "font_size": "14px",
                    "font_weight": "600",
                    "cursor": "pointer",
                    "font_family": "Inter, system-ui, sans-serif",
                    "_hover": {"background": "#2a0a0a"},
                },
            ),
            style={**t.CARD_STYLE, "padding": "24px", "width": "100%"},
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
    )
