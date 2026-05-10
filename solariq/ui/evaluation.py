# solariq/ui/evaluation.py
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


def _period_row(period: dict, index: int) -> rx.Component:
    cell_style = {"font_size": "13px", "color": t.FG, "padding": "8px 12px"}

    errors = AppState.evaluation_period_errors
    has_error_entry = errors.length() > index
    start_error = rx.cond(has_error_entry, errors[index]["start_time"], "")
    end_error = rx.cond(has_error_entry, errors[index]["end_time"], "")

    start_border = rx.cond(start_error != "", f"1px solid {t.FAIL}", f"1px solid {t.BORDER}")
    end_border = rx.cond(end_error != "", f"1px solid {t.FAIL}", f"1px solid {t.BORDER}")

    return rx.table.row(
        rx.table.cell(
            rx.cond(
                AppState.evaluation_today_mode & (index == 0),
                rx.text(
                    period["start_time"],
                    style={"font_size": "13px", "color": t.MUTED, "padding": "4px 8px"},
                ),
                rx.vstack(
                    rx.input(
                        value=period["start_time"],
                        on_change=lambda v: AppState.update_evaluation_period(index, "start_time", v),
                        on_blur=lambda v: AppState.validate_evaluation_period_time(index, "start_time", v),
                        style={"font_size": "13px", "width": "70px", "background": t.SECONDARY, "border": start_border, "border_radius": "4px", "padding": "4px 8px", "color": t.FG},
                    ),
                    rx.cond(
                        start_error != "",
                        rx.text(start_error, style={"font_size": "11px", "color": t.FAIL}),
                        rx.fragment(),
                    ),
                    spacing="0",
                    align="start",
                ),
            ),
            style=cell_style,
        ),
        rx.table.cell(
            rx.vstack(
                rx.input(
                    value=period["end_time"],
                    on_change=lambda v: AppState.update_evaluation_period(index, "end_time", v),
                    on_blur=lambda v: AppState.validate_evaluation_period_time(index, "end_time", v),
                    style={"font_size": "13px", "width": "70px", "background": t.SECONDARY, "border": end_border, "border_radius": "4px", "padding": "4px 8px", "color": t.FG},
                ),
                rx.cond(
                    end_error != "",
                    rx.text(end_error, style={"font_size": "11px", "color": t.FAIL}),
                    rx.fragment(),
                ),
                spacing="0",
                align="start",
            ),
            style=cell_style,
        ),
        rx.table.cell(
            rx.select(
                ["Charge", "Self Use"],
                value=period["mode"],
                on_change=lambda v: AppState.update_evaluation_period(index, "mode", v),
                style={"font_size": "13px", "background": t.SECONDARY, "color": t.FG},
            ),
            style=cell_style,
        ),
        rx.table.cell(
            rx.cond(
                period["mode"] == "Charge",
                rx.hstack(
                    rx.text("→", style={"color": t.MUTED, "font_size": "13px"}),
                    rx.input(
                        value=f"{period['target_soc_pct']}",
                        on_change=lambda v: AppState.update_evaluation_period(index, "target_soc_pct", v),
                        style={"font_size": "13px", "width": "55px", "background": t.SECONDARY, "border": f"1px solid {t.BORDER}", "border_radius": "4px", "padding": "4px 8px", "color": t.FG},
                    ),
                    rx.text("%", style={"color": t.MUTED, "font_size": "13px"}),
                    spacing="1",
                    align="center",
                ),
                rx.hstack(
                    rx.text("Min", style={"color": t.MUTED, "font_size": "13px"}),
                    rx.input(
                        value=f"{period['min_soc_pct']}",
                        on_change=lambda v: AppState.update_evaluation_period(index, "min_soc_pct", v),
                        style={"font_size": "13px", "width": "55px", "background": t.SECONDARY, "border": f"1px solid {t.BORDER}", "border_radius": "4px", "padding": "4px 8px", "color": t.FG},
                    ),
                    rx.text("%", style={"color": t.MUTED, "font_size": "13px"}),
                    spacing="1",
                    align="center",
                ),
            ),
            style=cell_style,
        ),
        rx.table.cell(
            rx.cond(
                period["mode"] == "Charge",
                rx.hstack(
                    rx.input(
                        value=f"{period['max_charge_kw']}",
                        on_change=lambda v: AppState.update_evaluation_period(index, "max_charge_kw", v),
                        style={"font_size": "13px", "width": "65px", "background": t.SECONDARY, "border": f"1px solid {t.BORDER}", "border_radius": "4px", "padding": "4px 8px", "color": t.FG},
                    ),
                    rx.text("kW", style={"color": t.MUTED, "font_size": "13px"}),
                    spacing="1",
                    align="center",
                ),
                rx.text("—", style={"font_size": "13px", "color": t.MUTED}),
            ),
            style=cell_style,
        ),
        rx.table.cell(
            rx.button(
                "✕",
                on_click=AppState.remove_evaluation_period(index),
                aria_label="Remove period",
                style={
                    "background": "transparent",
                    "color": t.FAIL,
                    "border": "none",
                    "cursor": "pointer",
                    "font_size": "14px",
                    "padding": "4px 8px",
                },
            ),
            style=cell_style,
        ),
        style={"border_bottom": f"1px solid {t.BORDER}", "_hover": {"background": t.SECONDARY}},
    )


def _agile_price_chart() -> rx.Component:
    return rx.box(
        _section_heading("Agile Rates (p/kWh)"),
        rx.recharts.composed_chart(
            rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
            rx.recharts.bar(data_key="import", name="Import", fill=t.CHART_PRICE, fill_opacity=0.7, radius=[2, 2, 0, 0]),
            rx.recharts.bar(data_key="export", name="Export", fill=t.CHART_EXPORT, fill_opacity=0.7, radius=[2, 2, 0, 0]),
            rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
            rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
            rx.recharts.legend(),
            rx.recharts.tooltip(),
            data=AppState.evaluation_agile_chart_data,
            width="100%",
            height=160,
            bar_size=20,
            bar_gap=-20,
        ),
        style={**t.CARD_STYLE, "padding": "20px", "margin_bottom": "20px", "width": "100%"},
    )


def _schedule_editor() -> rx.Component:
    header_cell_style = {
        "font_size": "11px",
        "font_weight": "600",
        "color": t.MUTED,
        "text_transform": "uppercase",
        "letter_spacing": "0.06em",
        "padding": "10px 12px",
        "background": t.SECONDARY,
    }

    return rx.vstack(
        _section_heading("Schedule"),
        rx.cond(
            AppState.evaluation_periods.length() > 0,
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Start", style=header_cell_style),
                        rx.table.column_header_cell("End", style=header_cell_style),
                        rx.table.column_header_cell("Mode", style=header_cell_style),
                        rx.table.column_header_cell("Target / Min SOC", style=header_cell_style),
                        rx.table.column_header_cell("Max Charge", style=header_cell_style),
                        rx.table.column_header_cell("", style=header_cell_style),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        AppState.evaluation_periods,
                        lambda period, i: _period_row(period, i),
                    )
                ),
                style={**t.CARD_STYLE, "width": "100%", "overflow": "hidden"},
                variant="surface",
            ),
            rx.text(
                "No periods defined. Add a period to get started.",
                style={"font_size": "13px", "color": t.MUTED},
            ),
        ),
        rx.hstack(
            rx.button(
                "+ Add Period",
                on_click=AppState.add_evaluation_period,
                disabled=~AppState.evaluation_can_add_period,
                style={
                    "background": t.SECONDARY,
                    "color": t.FG,
                    "border": f"1px solid {t.BORDER}",
                    "border_radius": "6px",
                    "padding": "6px 14px",
                    "font_size": "13px",
                    "cursor": "pointer",
                    "font_family": "Inter, system-ui, sans-serif",
                },
            ),
            rx.button(
                "Evaluate",
                on_click=AppState.evaluate_schedule,
                loading=AppState.evaluation_loading,
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
            spacing="3",
            margin_top="3",
        ),
        width="100%",
        align="start",
    )


def _comparison_callout() -> rx.Component:
    return rx.cond(
        AppState.strategy_valid_until != "",
        rx.box(
            rx.hstack(
                rx.text(
                    f"Optimizer estimate: £{AppState.estimated_cost_gbp}",
                    style={"font_size": "13px", "color": t.MUTED},
                ),
                rx.text("·", style={"color": t.MUTED}),
                rx.text(
                    f"Your schedule: £{AppState.evaluation_result_cost}",
                    style={"font_size": "13px", "color": t.FG, "font_weight": "600"},
                ),
                spacing="2",
                align="center",
            ),
            style={
                **t.CARD_STYLE,
                "padding": "12px 16px",
                "margin_bottom": "16px",
            },
        ),
        rx.fragment(),
    )


def evaluation_tab() -> rx.Component:
    return rx.vstack(
        # Mode toggle
        rx.hstack(
            rx.button(
                "Tomorrow",
                on_click=rx.cond(
                    AppState.evaluation_today_mode,
                    AppState.toggle_evaluation_today_mode,
                    rx.noop(),
                ),
                variant=rx.cond(AppState.evaluation_today_mode, "soft", "solid"),
                style={"font_size": "13px", "cursor": "pointer", "font_family": "Inter, system-ui, sans-serif"},
            ),
            rx.button(
                "Today from now",
                on_click=rx.cond(
                    AppState.evaluation_today_mode,
                    rx.noop(),
                    AppState.toggle_evaluation_today_mode,
                ),
                variant=rx.cond(AppState.evaluation_today_mode, "solid", "soft"),
                style={"font_size": "13px", "cursor": "pointer", "font_family": "Inter, system-ui, sans-serif"},
            ),
            spacing="1",
            margin_bottom="4",
        ),
        # Current slot info (today mode only)
        rx.cond(
            AppState.evaluation_today_mode,
            rx.text(
                f"Evaluating from {AppState.evaluation_current_slot_time} (current slot)",
                style={"font_size": "12px", "color": t.MUTED, "margin_bottom": "8px"},
            ),
            rx.fragment(),
        ),
        _agile_price_chart(),
        _schedule_editor(),
        # Error message
        rx.cond(
            AppState.evaluation_error != "",
            rx.box(
                rx.text(AppState.evaluation_error, style={"font_size": "13px", "color": t.FAIL}),
                style={
                    **t.CARD_STYLE,
                    "background": "#1a0a0a",
                    "border_color": t.FAIL,
                    "padding": "12px 16px",
                    "margin_top": "16px",
                },
            ),
            rx.fragment(),
        ),
        # Test mode warning (only relevant in Tomorrow mode — Today from now always uses today's data)
        rx.cond(
            AppState.test_strategy_mode & ~AppState.evaluation_today_mode,
            rx.box(
                rx.text(
                    "⚠ Test strategy mode is enabled — forecast data uses today's rates.",
                    style={"font_size": "13px", "color": "#f59e0b"},
                ),
                style={
                    **t.CARD_STYLE,
                    "background": "#1a1200",
                    "border_color": "#f59e0b",
                    "padding": "12px 16px",
                    "margin_top": "16px",
                },
            ),
            rx.fragment(),
        ),
        # Results section
        rx.cond(
            AppState.evaluation_has_result,
            rx.vstack(
                rx.divider(style={"margin": "20px 0", "border_color": t.BORDER}),
                _section_heading("Results"),
                _comparison_callout(),
                rx.hstack(
                    stat_card("Est. Cost", rx.text(f"£{AppState.evaluation_result_cost}")),
                    stat_card("Solar Forecast", rx.text(f"{AppState.evaluation_solar_kwh} kWh")),
                    stat_card("Grid Import", rx.text(f"{AppState.evaluation_grid_import_kwh} kWh")),
                    spacing="3",
                    wrap="wrap",
                    margin_bottom="6",
                ),
                rx.grid(
                    rx.box(
                        _section_heading("Agile Prices by Mode (p/kWh)"),
                        rx.recharts.bar_chart(
                            rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
                            rx.recharts.bar(
                                data_key="price_self_use_explicit",
                                name="Self Use",
                                fill=t.CHART_EXPORT,
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
                            data=AppState.evaluation_price_data,
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
                            data=AppState.evaluation_solar_data,
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
                align="start",
            ),
            rx.fragment(),
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
        align="start",
    )
