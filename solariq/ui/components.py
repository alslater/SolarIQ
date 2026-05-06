import reflex as rx
from solariq.ui import theme as t


def stat_card(label: str, value: rx.Component, subtitle: str = "") -> rx.Component:
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
        rx.box(
            value,
            style={
                "font_size": "22px",
                "font_weight": "700",
                "color": t.FG,
                "line_height": "1.2",
            },
        ),
        rx.cond(
            subtitle != "",
            rx.text(subtitle, style={"font_size": "12px", "color": t.MUTED, "margin_top": "4px"}),
            rx.fragment(),
        ),
        style={
            **t.CARD_STYLE,
            "padding": "16px 20px",
            "min_width": "140px",
        },
    )


def price_bar_chart(data: list[dict], title: str) -> rx.Component:
    return rx.box(
        rx.text(
            title,
            style={"font_size": "12px", "font_weight": "500", "color": t.MUTED, "margin_bottom": "8px"},
        ),
        rx.recharts.bar_chart(
            rx.recharts.cartesian_grid(stroke_dasharray="3 3", stroke=t.CHART_GRID),
            rx.recharts.bar(data_key="price", name="p/kWh", fill=t.CHART_PRICE, radius=[2, 2, 0, 0]),
            rx.recharts.x_axis(data_key="time", tick={"fill": t.CHART_MUTED, "fontSize": 10}, interval=5),
            rx.recharts.y_axis(tick={"fill": t.CHART_MUTED, "fontSize": 10}),
            rx.recharts.tooltip(),
            data=data,
            width="100%",
            height=160,
        ),
        width="100%",
    )


def strategy_table(periods: list[dict]) -> rx.Component:
    header_cell_style = {
        "font_size": "11px",
        "font_weight": "600",
        "color": t.MUTED,
        "text_transform": "uppercase",
        "letter_spacing": "0.06em",
        "padding": "10px 12px",
        "background": t.SECONDARY,
    }
    body_cell_style = {
        "font_size": "13px",
        "color": t.FG,
        "padding": "10px 12px",
    }

    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("Period", style=header_cell_style),
                rx.table.column_header_cell("Start", style=header_cell_style),
                rx.table.column_header_cell("End", style=header_cell_style),
                rx.table.column_header_cell("Mode", style=header_cell_style),
                rx.table.column_header_cell("Settings", style=header_cell_style),
                rx.table.column_header_cell("Avg Price", style=header_cell_style),
            )
        ),
        rx.table.body(
            rx.foreach(
                periods,
                lambda p: rx.table.row(
                    rx.table.cell(p["period_num"], style=body_cell_style),
                    rx.table.cell(p["start_time"], style=body_cell_style),
                    rx.table.cell(p["end_time"], style=body_cell_style),
                    rx.table.cell(
                        rx.cond(
                            p["mode"] == "Charge",
                            rx.box(
                                p["mode"],
                                style={
                                    "display": "inline-block",
                                    "background": "#0a3a52",
                                    "color": t.PRIMARY,
                                    "border": f"1px solid {t.ACCENT}",
                                    "border_radius": "9999px",
                                    "padding": "2px 10px",
                                    "font_size": "11px",
                                    "font_weight": "600",
                                },
                            ),
                            rx.cond(
                                p["mode"] == "Battery Standby",
                                rx.box(
                                    p["mode"],
                                    style={
                                        "display": "inline-block",
                                        "background": "#1e0a3c",
                                        "color": "#a855f7",
                                        "border": "1px solid #a855f7",
                                        "border_radius": "9999px",
                                        "padding": "2px 10px",
                                        "font_size": "11px",
                                        "font_weight": "600",
                                    },
                                ),
                                rx.box(
                                    p["mode"],
                                    style={
                                        "display": "inline-block",
                                        "background": "#0d2b1c",
                                        "color": t.PASS,
                                        "border": f"1px solid {t.PASS}",
                                        "border_radius": "9999px",
                                        "padding": "2px 10px",
                                        "font_size": "11px",
                                        "font_weight": "600",
                                    },
                                ),
                            ),
                        ),
                        style=body_cell_style,
                    ),
                    rx.table.cell(
                        rx.cond(
                            p["mode"] == "Charge",
                            rx.text(f"→ {p['target_soc_pct']}%  {p['max_charge_w']}W", style={"font_size": "13px"}),
                            rx.cond(
                                p["mode"] == "Battery Standby",
                                rx.text(f"Export @ {p['avg_price_p']}p", style={"font_size": "13px", "color": "#a855f7"}),
                                rx.cond(
                                    p["is_default"],
                                    rx.text("Default Self Use (10%)", style={"font_size": "13px", "color": t.MUTED}),
                                    rx.text(f"Min SOC {p['min_soc_pct']}%", style={"font_size": "13px"}),
                                ),
                            ),
                        ),
                        style=body_cell_style,
                    ),
                    rx.table.cell(
                        rx.cond(
                            p["mode"] == "Charge",
                            rx.text(f"{p['avg_price_p']}p", style={"font_size": "13px", "color": t.REVIEW}),
                            rx.cond(
                                p["mode"] == "Battery Standby",
                                rx.text(f"{p['avg_price_p']}p", style={"font_size": "13px", "color": "#a855f7"}),
                                rx.text("—", style={"font_size": "13px", "color": t.MUTED}),
                            ),
                        ),
                        style=body_cell_style,
                    ),
                    style={"border_bottom": f"1px solid {t.BORDER}", "_hover": {"background": t.SECONDARY}},
                ),
            )
        ),
        style={**t.CARD_STYLE, "width": "100%", "border_collapse": "collapse", "overflow": "hidden"},
        variant="surface",
    )
