import reflex as rx
from solariq.ui.state import AppState
from solariq.ui.today import today_tab
from solariq.ui.tomorrow import tomorrow_tab
from solariq.ui.history import history_tab
from solariq.ui.settings import settings_tab
from solariq.ui.inverter import inverter_tab
from solariq.ui.evaluation import evaluation_tab
from solariq.ui.auth import auth_loading_view, bootstrap_view, login_view
from solariq.ui import theme as t


def _nav_item(label: str, icon: str, page_key: str) -> rx.Component:
    is_active = AppState.current_page == page_key
    return rx.box(
        rx.hstack(
            rx.icon(
                icon,
                size=16,
                style={"min_width": "20px", "flex_shrink": "0"},
            ),
            rx.cond(
                AppState.sidebar_collapsed,
                rx.fragment(),
                rx.text(
                    label,
                    style={
                        "font_size": "14px",
                        "font_weight": "500",
                        "font_family": "Inter, system-ui, sans-serif",
                    },
                ),
            ),
            spacing="3",
            align="center",
            justify=rx.cond(AppState.sidebar_collapsed, "center", "start"),
            width="100%",
        ),
        on_click=AppState.set_page(page_key),
        cursor="pointer",
        padding=rx.cond(AppState.sidebar_collapsed, "10px 12px", "10px 20px"),
        border_left=rx.cond(is_active, f"3px solid {t.PRIMARY}", "3px solid transparent"),
        background=rx.cond(is_active, "#0d1e33", "transparent"),
        color=rx.cond(is_active, t.PRIMARY, t.SIDEBAR_MUTED),
        _hover={"background": "#0d1e33", "color": t.SIDEBAR_FG},
    )


def _sidebar() -> rx.Component:
    return rx.box(
        # Logo
        rx.hstack(
            rx.hstack(
                rx.icon("sun", size=20, color=t.SIDEBAR_FG),
                rx.cond(
                    AppState.sidebar_collapsed,
                    rx.fragment(),
                    rx.heading(
                        "SolarIQ",
                        style={
                            "font_size": "17px",
                            "font_weight": "700",
                            "color": t.SIDEBAR_FG,
                            "font_family": "Inter, system-ui, sans-serif",
                            "letter_spacing": "-0.02em",
                        },
                    ),
                ),
                spacing="2",
                align="center",
            ),
            rx.button(
                rx.icon(
                    rx.cond(AppState.sidebar_collapsed, "panel-left-open", "panel-left-close"),
                    size=14,
                    color=t.SIDEBAR_MUTED,
                ),
                on_click=AppState.toggle_sidebar,
                style={
                    "background": "transparent",
                    "border": f"1px solid {t.BORDER}",
                    "border_radius": "6px",
                    "cursor": "pointer",
                    "padding": "6px",
                    "_hover": {"border_color": t.PRIMARY},
                },
            ),
            justify="between",
            align="center",
            padding=rx.cond(AppState.sidebar_collapsed, "0 10px", "0 20px"),
            height="56px",
            border_bottom=f"1px solid {t.BORDER}",
        ),
        # Nav items
        rx.vstack(
            _nav_item("Today", "layout-dashboard", "today"),
            _nav_item("History", "chart-line", "history"),
            _nav_item("Inverter", "cpu", "inverter"),
            _nav_item("Charging Strategy", "battery-charging", "tomorrow"),
            _nav_item("Evaluation", "flask-conical", "evaluation"),
            _nav_item("Settings", "settings", "settings"),
            spacing="1",
            padding_top="12px",
            align="stretch",
            width="100%",
        ),
        rx.spacer(),
        rx.box(
            rx.vstack(
                rx.cond(
                    AppState.sidebar_collapsed,
                    rx.fragment(),
                    rx.text(
                        AppState.current_user,
                        style={"font_size": "12px", "font_weight": "600", "color": t.SIDEBAR_FG},
                    ),
                ),
                rx.button(
                    rx.cond(
                        AppState.sidebar_collapsed,
                        rx.icon("log-out", size=14, color=t.SIDEBAR_MUTED),
                        rx.text("Sign out"),
                    ),
                    on_click=AppState.logout,
                    style={
                        "background": "transparent",
                        "border": f"1px solid {t.BORDER}",
                        "border_radius": "6px",
                        "cursor": "pointer",
                        "padding": rx.cond(AppState.sidebar_collapsed, "6px", "4px 10px"),
                        "font_size": "12px",
                        "color": t.SIDEBAR_MUTED,
                        "_hover": {"border_color": t.PRIMARY, "color": t.SIDEBAR_FG},
                        "width": rx.cond(AppState.sidebar_collapsed, "auto", "100%"),
                    },
                ),
                spacing="2",
                align=rx.cond(AppState.sidebar_collapsed, "center", "start"),
                width="100%",
            ),
            padding=rx.cond(AppState.sidebar_collapsed, "12px 10px", "12px 20px"),
            border_top=f"1px solid {t.BORDER}",
            width="100%",
        ),
        # Colour mode toggle
        rx.box(
            rx.button(
                rx.color_mode_cond(
                    light=rx.icon("moon", size=14, color=t.SIDEBAR_MUTED),
                    dark=rx.icon("sun", size=14, color=t.SIDEBAR_MUTED),
                ),
                on_click=rx.toggle_color_mode,
                style={
                    "background": "transparent",
                    "border": f"1px solid {t.BORDER}",
                    "border_radius": "6px",
                    "cursor": "pointer",
                    "padding": "6px 10px",
                    "width": "100%",
                    "_hover": {"border_color": t.PRIMARY},
                },
            ),
            padding=rx.cond(AppState.sidebar_collapsed, "16px 10px", "16px 20px"),
            border_top=f"1px solid {t.BORDER}",
        ),
        style={
            "background": t.SIDEBAR,
            "width": rx.cond(AppState.sidebar_collapsed, "72px", "220px"),
            "min_width": rx.cond(AppState.sidebar_collapsed, "72px", "220px"),
            "min_height": "100vh",
            "border_right": f"1px solid {t.BORDER}",
            "display": "flex",
            "flex_direction": "column",
            "transition": "width 160ms ease",
        },
    )


def index() -> rx.Component:
    return rx.box(
        rx.cond(
            AppState.auth_ready == False,
            auth_loading_view(),
            rx.cond(
                AppState.needs_initial_user,
                bootstrap_view(),
                rx.cond(
                    AppState.is_authenticated == False,
                    login_view(),
                    rx.hstack(
                        _sidebar(),
                        rx.box(
                            rx.cond(
                                AppState.current_page == "today",
                                today_tab(),
                                rx.cond(
                                    AppState.current_page == "tomorrow",
                                    tomorrow_tab(),
                                    rx.cond(
                                        AppState.current_page == "history",
                                        history_tab(),
                                        rx.cond(
                                            AppState.current_page == "inverter",
                                            inverter_tab(),
                                            rx.cond(
                                                AppState.current_page == "evaluation",
                                                evaluation_tab(),
                                                settings_tab(),
                                            ),
                                        ),
                                    ),
                                ),
                            ),
                            style={
                                "flex": "1",
                                "min_height": "100vh",
                                "overflow_y": "auto",
                                "background": t.BG,
                            },
                        ),
                        align="start",
                        spacing="0",
                        style={
                            "background": t.BG,
                            "font_family": "Inter, system-ui, sans-serif",
                            "min_height": "100vh",
                        },
                    ),
                ),
            ),
        ),
        style={"min_height": "100vh"},
    )


app = rx.App(
    stylesheets=["compli.css"],
    toaster=rx.toast.provider(position="top-right"),
    head_components=[
        rx.el.link(rel="icon", type="image/svg+xml", href="/favicon.svg"),
    ],
)
app.add_page(index, route="/", title="SolarIQ", on_load=AppState.on_load)
