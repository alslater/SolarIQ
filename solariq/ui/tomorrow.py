import reflex as rx
from solariq.ui.state import AppState
from solariq.ui.components import stat_card, price_bar_chart, strategy_table
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


def _last_updated_card() -> rx.Component:
    return rx.box(
        rx.text(
            "Valid Until",
            style={"font_size": "11px", "font_weight": "500", "color": t.MUTED, "text_transform": "uppercase", "letter_spacing": "0.06em", "margin_bottom": "4px"},
        ),
        rx.text(AppState.strategy_valid_until_str, style={"font_size": "13px", "color": t.FG, "margin_bottom": "10px"}),
        rx.button(
            "Recalculate",
            on_click=AppState.refresh_strategy,
            loading=AppState.strategy_loading,
            style={
                "background": t.PRIMARY,
                "color": "#060a12",
                "border": "none",
                "border_radius": "6px",
                "padding": "6px 14px",
                "font_size": "13px",
                "font_weight": "600",
                "cursor": "pointer",
                "font_family": "Inter, system-ui, sans-serif",
                "_hover": {"background": t.ACCENT},
            },
        ),
        style={**t.CARD_STYLE, "padding": "16px 20px", "min_width": "160px"},
    )


def tomorrow_tab() -> rx.Component:
    return rx.vstack(
        # Summary bar
        rx.hstack(
            stat_card("Est. Cost", rx.text(f"£{AppState.estimated_cost_gbp}")),
            stat_card("Solar Forecast", rx.text(f"{AppState.solar_forecast_kwh} kWh")),
            stat_card("Grid Import", rx.text(f"{AppState.grid_import_kwh} kWh")),
            _last_updated_card(),
            spacing="3",
            wrap="wrap",
            margin_bottom="6",
        ),
        # Error message
        rx.cond(
            AppState.strategy_error != "",
            rx.box(
                rx.text(AppState.strategy_error, style={"font_size": "13px", "color": t.FAIL}),
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
        # Solar forecast warning
        rx.cond(
            AppState.strategy_solar_estimated,
            rx.box(
                rx.text(
                    "⚠ Solar forecast unavailable — strategy computed with zero solar. Cost estimate will be conservative.",
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
        # Test mode warning
        rx.cond(
            AppState.test_strategy_mode,
            rx.box(
                rx.text(
                    "⚠ Test strategy mode is enabled — tomorrow's rates are substituted with today's. Disable test_strategy_mode in solariq.ini for production use.",
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
        # Loading indicator
        rx.cond(
            AppState.strategy_loading,
            rx.hstack(
                rx.spinner(style={"color": t.PRIMARY}),
                rx.text("Calculating strategy…", style={"font_size": "13px", "color": t.MUTED}),
                spacing="2",
                align="center",
                margin_bottom="4",
            ),
            rx.fragment(),
        ),
        # Strategy table
        rx.cond(
            AppState.strategy_periods,
            rx.box(
                _section_heading("Charging Strategy"),
                rx.hstack(
                    rx.text(
                        "Filter Rows:",
                        style={
                            "font_size": "11px",
                            "font_weight": "600",
                            "color": t.MUTED,
                            "text_transform": "uppercase",
                            "letter_spacing": "0.06em",
                        },
                    ),
                    rx.button(
                        "Self Use (Implicit)",
                        on_click=AppState.toggle_show_self_use_implicit,
                        size="1",
                        variant=rx.cond(AppState.show_self_use_implicit, "solid", "soft"),
                        style={"font_size": "11px", "cursor": "pointer"},
                    ),
                    rx.button(
                        "Self Use (Explicit)",
                        on_click=AppState.toggle_show_self_use_explicit,
                        size="1",
                        variant=rx.cond(AppState.show_self_use_explicit, "solid", "soft"),
                        style={"font_size": "11px", "cursor": "pointer"},
                    ),
                    rx.button(
                        "Charge",
                        on_click=AppState.toggle_show_charge,
                        size="1",
                        variant=rx.cond(AppState.show_charge, "solid", "soft"),
                        style={"font_size": "11px", "cursor": "pointer"},
                    ),
                    rx.separator(orientation="vertical", style={"height": "16px"}),
                    rx.text(
                        "Sort:",
                        style={
                            "font_size": "11px",
                            "font_weight": "600",
                            "color": t.MUTED,
                            "text_transform": "uppercase",
                            "letter_spacing": "0.06em",
                        },
                    ),
                    rx.button(
                        "By Start Time",
                        on_click=AppState.toggle_sort_strategy_by_time,
                        size="1",
                        variant=rx.cond(AppState.sort_strategy_by_time, "solid", "soft"),
                        style={"font_size": "11px", "cursor": "pointer"},
                    ),
                    spacing="2",
                    align="center",
                    width="100%",
                    wrap="wrap",
                    margin_bottom="2",
                ),
                strategy_table(AppState.filtered_strategy_periods),
                margin_bottom="4",
                width="100%",
            ),
            rx.text("No strategy calculated yet.", style={"font_size": "13px", "color": t.MUTED}),
        ),
        # Charts
        rx.grid(
            rx.box(
                _section_heading("Agile Prices by Planned Mode (p/kWh)"),
                rx.recharts.bar_chart(
                    rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                    rx.recharts.bar(
                        data_key="price_self_use_implicit",
                        name="Self Use (Implicit)",
                        fill=t.CHART_EXPORT,
                        radius=[2, 2, 0, 0],
                        stack_id="price",
                    ),
                    rx.recharts.bar(
                        data_key="price_self_use_explicit",
                        name="Self Use (Explicit)",
                        fill="#f59e0b",
                        radius=[2, 2, 0, 0],
                        stack_id="price",
                    ),
                    rx.recharts.bar(
                        data_key="price_charge",
                        name="Charge",
                        fill=t.CHART_PRICE,
                        radius=[2, 2, 0, 0],
                        stack_id="price",
                    ),
                    rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
                    rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                    rx.recharts.legend(),
                    rx.recharts.tooltip(),
                    data=AppState.tomorrow_price_data,
                    width="100%",
                    height=200,
                ),
                style={**t.CARD_STYLE, "padding": "20px"},
            ),
            rx.box(
                _section_heading("Solar Forecast & Battery SOC (%)"),
                rx.recharts.composed_chart(
                    rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                    rx.recharts.bar(data_key="solar", name="Solar kWh", fill=t.CHART_SOLAR, radius=[2, 2, 0, 0]),
                    rx.recharts.line(
                        data_key="soc_pct",
                        name="Battery SOC %",
                        stroke=t.CHART_EXPORT,
                        stroke_width=2,
                        dot=False,
                        y_axis_id="right",
                    ),
                    rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
                    rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                    rx.recharts.y_axis(y_axis_id="right", orientation="right", tick={"fill": t.CHART_MUTED, "fontSize": 10}),
                    rx.recharts.legend(),
                    rx.recharts.tooltip(),
                    data=AppState.tomorrow_solar_data,
                    width="100%",
                    height=200,
                ),
                style={**t.CARD_STYLE, "padding": "20px"},
            ),
            columns="2",
            spacing="4",
            width="100%",
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
    )
