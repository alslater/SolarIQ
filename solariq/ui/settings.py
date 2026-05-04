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
        # Cache section (admin only)
        rx.cond(
            AppState.current_user_is_admin,
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
            rx.fragment(),
        ),
        # Account section
        rx.box(
            rx.text(
                "Account",
                style={
                    "font_size": "13px",
                    "font_weight": "600",
                    "color": t.MUTED,
                    "text_transform": "uppercase",
                    "letter_spacing": "0.06em",
                    "margin_bottom": "16px",
                },
            ),
            rx.hstack(
                rx.text("Signed in as:", style={"font_size": "13px", "color": t.MUTED}),
                rx.text(AppState.current_user, style={"font_size": "13px", "color": t.FG, "font_weight": "600"}),
                spacing="2",
                margin_bottom="16px",
            ),
            rx.vstack(
                rx.input(
                    on_change=AppState.set_current_password,
                    type="password",
                    placeholder="Current password",
                    style={
                        "width": "100%",
                        "max_width": "420px",
                        "background": t.SECONDARY,
                        "border": f"1px solid {t.BORDER}",
                        "border_radius": "8px",
                        "padding": "10px 12px",
                        "font_size": "13px",
                        "color": t.FG,
                    },
                ),
                rx.cond(
                    AppState.current_password_error != "",
                    rx.text(
                        AppState.current_password_error,
                        style={"font_size": "12px", "color": t.FAIL},
                    ),
                    rx.fragment(),
                ),
                rx.input(
                    on_change=AppState.set_new_password,
                    type="password",
                    placeholder="New password",
                    style={
                        "width": "100%",
                        "max_width": "420px",
                        "background": t.SECONDARY,
                        "border": f"1px solid {t.BORDER}",
                        "border_radius": "8px",
                        "padding": "10px 12px",
                        "font_size": "13px",
                        "color": t.FG,
                    },
                ),
                rx.cond(
                    AppState.new_password_error != "",
                    rx.text(
                        AppState.new_password_error,
                        style={"font_size": "12px", "color": t.FAIL},
                    ),
                    rx.fragment(),
                ),
                rx.input(
                    on_change=AppState.set_new_password_confirm,
                    type="password",
                    placeholder="Confirm new password",
                    style={
                        "width": "100%",
                        "max_width": "420px",
                        "background": t.SECONDARY,
                        "border": f"1px solid {t.BORDER}",
                        "border_radius": "8px",
                        "padding": "10px 12px",
                        "font_size": "13px",
                        "color": t.FG,
                    },
                ),
                rx.cond(
                    AppState.new_password_confirm_error != "",
                    rx.text(
                        AppState.new_password_confirm_error,
                        style={"font_size": "12px", "color": t.FAIL},
                    ),
                    rx.fragment(),
                ),
                spacing="2",
                width="100%",
                align="start",
                margin_bottom="14px",
            ),
            rx.hstack(
                rx.button(
                    "Update Password",
                    on_click=AppState.update_my_password,
                    style={
                        "background": t.PRIMARY,
                        "color": "#060a12",
                        "border": "none",
                        "border_radius": "6px",
                        "padding": "8px 16px",
                        "font_size": "13px",
                        "font_weight": "600",
                        "cursor": "pointer",
                        "font_family": "Inter, system-ui, sans-serif",
                        "_hover": {"background": t.ACCENT},
                    },
                ),
                rx.button(
                    "Sign Out",
                    on_click=AppState.logout,
                    style={
                        "background": "transparent",
                        "color": t.MUTED,
                        "border": f"1px solid {t.BORDER}",
                        "border_radius": "6px",
                        "padding": "8px 16px",
                        "font_size": "13px",
                        "font_weight": "600",
                        "cursor": "pointer",
                        "font_family": "Inter, system-ui, sans-serif",
                        "_hover": {"border_color": t.PRIMARY, "color": t.FG},
                    },
                ),
                spacing="2",
            ),
            rx.cond(
                AppState.account_form_error != "",
                rx.text(
                    AppState.account_form_error,
                    style={"font_size": "13px", "color": t.FAIL, "margin_top": "12px"},
                ),
                rx.fragment(),
            ),
            style={**t.CARD_STYLE, "padding": "24px", "width": "100%"},
        ),
        # User management section (admin only)
        rx.cond(
            AppState.current_user_is_admin,
            rx.box(
                rx.text(
                    "Users",
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
                    "Create and remove application users.",
                    style={"font_size": "13px", "color": t.MUTED, "margin_bottom": "16px"},
                ),
                rx.vstack(
                    rx.input(
                        value=AppState.new_user_username,
                        on_change=AppState.set_new_user_username,
                        placeholder="Username",
                        style={
                            "width": "100%",
                            "max_width": "420px",
                            "background": t.SECONDARY,
                            "border": f"1px solid {t.BORDER}",
                            "border_radius": "8px",
                            "padding": "10px 12px",
                            "font_size": "13px",
                            "color": t.FG,
                        },
                    ),
                    rx.cond(
                        AppState.new_user_username_error != "",
                        rx.text(
                            AppState.new_user_username_error,
                            style={"font_size": "12px", "color": t.FAIL},
                        ),
                        rx.fragment(),
                    ),
                    rx.input(
                        on_change=AppState.set_new_user_password,
                        type="password",
                        placeholder="Password",
                        style={
                            "width": "100%",
                            "max_width": "420px",
                            "background": t.SECONDARY,
                            "border": f"1px solid {t.BORDER}",
                            "border_radius": "8px",
                            "padding": "10px 12px",
                            "font_size": "13px",
                            "color": t.FG,
                        },
                    ),
                    rx.cond(
                        AppState.new_user_password_error != "",
                        rx.text(
                            AppState.new_user_password_error,
                            style={"font_size": "12px", "color": t.FAIL},
                        ),
                        rx.fragment(),
                    ),
                    rx.input(
                        on_change=AppState.set_new_user_password_confirm,
                        type="password",
                        placeholder="Confirm password",
                        style={
                            "width": "100%",
                            "max_width": "420px",
                            "background": t.SECONDARY,
                            "border": f"1px solid {t.BORDER}",
                            "border_radius": "8px",
                            "padding": "10px 12px",
                            "font_size": "13px",
                            "color": t.FG,
                        },
                    ),
                    rx.cond(
                        AppState.new_user_password_confirm_error != "",
                        rx.text(
                            AppState.new_user_password_confirm_error,
                            style={"font_size": "12px", "color": t.FAIL},
                        ),
                        rx.fragment(),
                    ),
                    rx.hstack(
                        rx.switch(
                            checked=AppState.new_user_is_admin,
                            on_change=AppState.set_new_user_is_admin,
                        ),
                        rx.text(
                            "Create as administrator",
                            style={"font_size": "13px", "color": t.FG},
                        ),
                        spacing="2",
                        align="center",
                    ),
                    rx.button(
                        "Create User",
                        on_click=AppState.create_managed_user,
                        style={
                            "background": t.PRIMARY,
                            "color": "#060a12",
                            "border": "none",
                            "border_radius": "6px",
                            "padding": "8px 16px",
                            "font_size": "13px",
                            "font_weight": "600",
                            "cursor": "pointer",
                            "font_family": "Inter, system-ui, sans-serif",
                            "_hover": {"background": t.ACCENT},
                        },
                    ),
                    spacing="2",
                    width="100%",
                    align="start",
                    margin_bottom="16px",
                ),
                rx.cond(
                    AppState.admin_form_error != "",
                    rx.text(
                        AppState.admin_form_error,
                        style={"font_size": "13px", "color": t.FAIL, "margin_bottom": "12px"},
                    ),
                    rx.fragment(),
                ),
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("User"),
                            rx.table.column_header_cell("Role"),
                            rx.table.column_header_cell("Action"),
                        )
                    ),
                    rx.table.body(
                        rx.foreach(
                            AppState.user_list,
                            lambda user: rx.table.row(
                                rx.table.cell(
                                    rx.text(user["username"], style={"font_size": "13px", "color": t.FG}),
                                ),
                                rx.table.cell(
                                    rx.cond(
                                        user["is_admin"],
                                        rx.box(
                                            "Admin",
                                            style={
                                                "display": "inline-block",
                                                "background": "#0a3a52",
                                                "color": t.PRIMARY,
                                                "border": f"1px solid {t.ACCENT}",
                                                "border_radius": "9999px",
                                                "padding": "2px 10px",
                                                "font_size": "11px",
                                                "font_weight": "700",
                                            },
                                        ),
                                        rx.box(
                                            "User",
                                            style={
                                                "display": "inline-block",
                                                "background": t.SECONDARY,
                                                "color": t.MUTED,
                                                "border": f"1px solid {t.BORDER}",
                                                "border_radius": "9999px",
                                                "padding": "2px 10px",
                                                "font_size": "11px",
                                                "font_weight": "600",
                                            },
                                        ),
                                    ),
                                ),
                                rx.table.cell(
                                    rx.cond(
                                        user["username"] == AppState.current_user,
                                        rx.text(
                                            "Current user",
                                            style={"font_size": "12px", "color": t.MUTED},
                                        ),
                                        rx.hstack(
                                            rx.cond(
                                                user["is_admin"],
                                                rx.button(
                                                    "Demote",
                                                    on_click=AppState.set_managed_user_admin_role(
                                                        user["username"],
                                                        False,
                                                    ),
                                                    style={
                                                        "background": "transparent",
                                                        "color": t.PRIMARY,
                                                        "border": f"1px solid {t.ACCENT}",
                                                        "border_radius": "6px",
                                                        "padding": "4px 8px",
                                                        "font_size": "12px",
                                                        "font_weight": "600",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                                rx.button(
                                                    "Promote",
                                                    on_click=AppState.set_managed_user_admin_role(
                                                        user["username"],
                                                        True,
                                                    ),
                                                    style={
                                                        "background": "transparent",
                                                        "color": t.PRIMARY,
                                                        "border": f"1px solid {t.ACCENT}",
                                                        "border_radius": "6px",
                                                        "padding": "4px 8px",
                                                        "font_size": "12px",
                                                        "font_weight": "600",
                                                        "cursor": "pointer",
                                                    },
                                                ),
                                            ),
                                            rx.alert_dialog.root(
                                                rx.alert_dialog.trigger(
                                                    rx.button(
                                                        rx.icon("trash-2", size=14),
                                                        style={
                                                            "background": "transparent",
                                                            "color": t.FAIL,
                                                            "border": f"1px solid {t.FAIL}",
                                                            "border_radius": "6px",
                                                            "padding": "4px 8px",
                                                            "cursor": "pointer",
                                                            "_hover": {"background": "#2a0a0a"},
                                                        },
                                                    ),
                                                ),
                                                rx.alert_dialog.content(
                                                    rx.alert_dialog.title("Delete user?"),
                                                    rx.alert_dialog.description(
                                                        rx.hstack(
                                                            rx.text("Are you sure you want to delete"),
                                                            rx.text(user["username"], style={"font_weight": "700"}),
                                                            rx.text("? This action cannot be undone."),
                                                            spacing="1",
                                                            wrap="wrap",
                                                        ),
                                                    ),
                                                    rx.hstack(
                                                        rx.alert_dialog.cancel(
                                                            rx.button(
                                                                "Cancel",
                                                                style={
                                                                    "background": "transparent",
                                                                    "color": t.MUTED,
                                                                    "border": f"1px solid {t.BORDER}",
                                                                    "border_radius": "6px",
                                                                    "padding": "6px 12px",
                                                                    "font_size": "12px",
                                                                    "font_weight": "600",
                                                                    "cursor": "pointer",
                                                                },
                                                            ),
                                                        ),
                                                        rx.alert_dialog.action(
                                                            rx.button(
                                                                "Delete",
                                                                on_click=AppState.delete_managed_user(user["username"]),
                                                                style={
                                                                    "background": "#2a0a0a",
                                                                    "color": t.FAIL,
                                                                    "border": f"1px solid {t.FAIL}",
                                                                    "border_radius": "6px",
                                                                    "padding": "6px 12px",
                                                                    "font_size": "12px",
                                                                    "font_weight": "700",
                                                                    "cursor": "pointer",
                                                                },
                                                            ),
                                                        ),
                                                        spacing="2",
                                                        justify="end",
                                                        margin_top="14px",
                                                    ),
                                                ),
                                            ),
                                            spacing="2",
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                style={**t.CARD_STYLE, "padding": "24px", "width": "100%"},
            ),
            rx.fragment(),
        ),
        width="100%",
        padding="6",
        style={"background": t.BG},
    )
