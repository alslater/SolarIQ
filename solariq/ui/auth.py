import reflex as rx

from solariq.ui import theme as t
from solariq.ui.state import AppState


def _field(
    label: str,
    on_change,
    *,
    value=None,
    placeholder: str = "",
    password: bool = False,
    autocomplete: str | None = None,
    name: str | None = None,
) -> rx.Component:
    return rx.vstack(
        rx.text(
            label,
            style={
                "font_size": "12px",
                "font_weight": "600",
                "color": t.MUTED,
                "text_transform": "uppercase",
                "letter_spacing": "0.06em",
            },
        ),
        rx.input(
            on_change=on_change,
            placeholder=placeholder,
            type="password" if password else "text",
            name=name,
            custom_attrs=({"autocomplete": autocomplete} if autocomplete is not None else {}),
            **({"value": value} if value is not None else {}),
            style={
                "width": "100%",
                "background": t.SECONDARY,
                "border": f"1px solid {t.BORDER}",
                "border_radius": "8px",
                "padding": "10px 12px",
                "color": t.FG,
                "font_size": "14px",
            },
        ),
        spacing="1",
        width="100%",
    )


def login_view() -> rx.Component:
    return rx.center(
        rx.box(
            rx.vstack(
                rx.heading(
                    "Sign in to SolarIQ",
                    style={
                        "font_size": "26px",
                        "font_weight": "700",
                        "font_family": "Inter, system-ui, sans-serif",
                        "color": t.FG,
                    },
                ),
                rx.text(
                    "Use your SolarIQ username and password.",
                    style={"font_size": "14px", "color": t.MUTED},
                ),
                _field(
                    "Username",
                    AppState.set_login_username,
                    value=AppState.login_username,
                    placeholder="admin",
                    autocomplete="username",
                    name="username",
                ),
                _field(
                    "Password",
                    AppState.set_login_password,
                    password=True,
                    autocomplete="current-password",
                    name="password",
                ),
                rx.cond(
                    AppState.auth_error != "",
                    rx.text(AppState.auth_error, style={"color": t.FAIL, "font_size": "13px"}),
                    rx.fragment(),
                ),
                rx.button(
                    "Sign in",
                    on_click=AppState.login,
                    style={
                        "width": "100%",
                        "background": t.PRIMARY,
                        "color": "#06111d",
                        "font_weight": "700",
                        "padding": "10px 16px",
                        "border_radius": "8px",
                        "cursor": "pointer",
                        "_hover": {"background": t.ACCENT},
                    },
                ),
                spacing="3",
                width="100%",
            ),
            style={
                **t.CARD_STYLE,
                "width": "100%",
                "max_width": "420px",
                "padding": "28px",
            },
        ),
        style={
            "min_height": "100vh",
            "padding": "24px",
            "background": t.BG,
        },
    )


def bootstrap_view() -> rx.Component:
    return rx.center(
        rx.box(
            rx.vstack(
                rx.heading(
                    "Create the first SolarIQ user",
                    style={
                        "font_size": "26px",
                        "font_weight": "700",
                        "font_family": "Inter, system-ui, sans-serif",
                        "color": t.FG,
                    },
                ),
                rx.text(
                    "No users were found. This account will be created as an administrator.",
                    style={"font_size": "14px", "color": t.MUTED},
                ),
                _field(
                    "Username",
                    AppState.set_setup_username,
                    value=AppState.setup_username,
                    placeholder="admin",
                    autocomplete="off",
                    name="username",
                ),
                _field(
                    "Password",
                    AppState.set_setup_password,
                    password=True,
                    autocomplete="off",
                    name="password",
                ),
                _field(
                    "Confirm password",
                    AppState.set_setup_password_confirm,
                    password=True,
                    autocomplete="off",
                    name="confirm-password",
                ),
                rx.cond(
                    AppState.auth_error != "",
                    rx.text(AppState.auth_error, style={"color": t.FAIL, "font_size": "13px"}),
                    rx.fragment(),
                ),
                rx.button(
                    "Create account",
                    on_click=AppState.create_initial_user,
                    style={
                        "width": "100%",
                        "background": t.PRIMARY,
                        "color": "#06111d",
                        "font_weight": "700",
                        "padding": "10px 16px",
                        "border_radius": "8px",
                        "cursor": "pointer",
                        "_hover": {"background": t.ACCENT},
                    },
                ),
                spacing="3",
                width="100%",
            ),
            style={
                **t.CARD_STYLE,
                "width": "100%",
                "max_width": "520px",
                "padding": "28px",
            },
        ),
        style={
            "min_height": "100vh",
            "padding": "24px",
            "background": t.BG,
        },
    )


def auth_loading_view() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.spinner(size="3"),
            rx.text("Loading authentication...", style={"color": t.MUTED, "font_size": "14px"}),
            spacing="3",
            align="center",
        ),
        style={"min_height": "100vh", "background": t.BG},
    )
