import logging

import reflex as rx

from solariq.auth import (
    authenticate_user,
    change_password,
    create_initial_user,
    create_session,
    create_user,
    create_user_as_admin,
    delete_user_as_admin,
    get_session_user,
    has_admin_users,
    has_users,
    init_auth_db,
    invalidate_session,
    list_users_with_roles,
    promote_user_to_admin,
    set_user_admin_role_as_admin,
    validate_password_strength,
)
from solariq.config import load_config
from solariq.ui.state_common import get_config


def _auth_cookie_secure_flag() -> bool:
    try:
        return bool(load_config().app.auth_cookie_secure)
    except Exception:
        return False


AUTH_COOKIE_SECURE = _auth_cookie_secure_flag()
logger = logging.getLogger(__name__)


class AuthState(rx.State):
    auth_token: str = rx.Cookie(
        "",
        name="solariq_auth_token",
        path="/",
        max_age=60 * 60 * 24 * 30,
        secure=AUTH_COOKIE_SECURE,
        same_site="lax",
    )

    login_username: str = ""
    setup_username: str = ""
    new_user_username: str = ""
    new_user_is_admin: bool = False
    user_list: list[dict] = []

    auth_error: str = ""
    auth_ready: bool = True
    auth_users_exist: bool = True
    account_form_error: str = ""
    admin_form_error: str = ""
    current_user: str = ""
    current_user_is_admin: bool = False
    current_password_error: str = ""
    new_password_error: str = ""
    new_password_confirm_error: str = ""
    new_user_username_error: str = ""
    new_user_password_error: str = ""
    new_user_password_confirm_error: str = ""

    _login_password: str = ""
    _setup_password: str = ""
    _setup_password_confirm: str = ""
    _new_user_password: str = ""
    _new_user_password_confirm: str = ""
    _current_password: str = ""
    _new_password: str = ""
    _new_password_confirm: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.current_user)

    @rx.var
    def needs_initial_user(self) -> bool:
        return self.auth_ready and not self.auth_users_exist

    def _post_auth_success_events(self) -> list:
        return []

    def _login_impl(self):
        try:
            db_path = get_config().app.auth_db_path
            init_auth_db(db_path)
            self.auth_users_exist = has_users(db_path)
            self.auth_error = ""

            if not self.auth_users_exist:
                self.auth_error = "No users exist yet. Create the first user to continue."
                return

            try:
                user = authenticate_user(db_path, self.login_username, self._login_password)
            except ValueError as exc:
                self.auth_error = str(exc)
                return

            if user is None:
                self.auth_error = "Invalid username or password."
                return

            recovered_admin = False
            if not has_admin_users(db_path):
                user = promote_user_to_admin(db_path, user.username)
                recovered_admin = True

            token = create_session(db_path, user.id)
            self.auth_token = token
            self.current_user = user.username
            self.current_user_is_admin = user.is_admin
            self._login_password = ""
            self.auth_error = ""
            self.refresh_user_list()

            if recovered_admin:
                return [
                    rx.toast.warning(
                        "No administrators were found. This user has been promoted to admin.",
                        duration=6000,
                        close_button=True,
                    ),
                    *self._post_auth_success_events(),
                ]

            return self._post_auth_success_events()
        except Exception as exc:
            logger.exception("Authentication failed during login initialization: %s", exc)
            self.auth_error = "Authentication failed to initialize; check server logs."
            return

    def _create_initial_user_impl(self):
        try:
            db_path = get_config().app.auth_db_path
            init_auth_db(db_path)

            if has_users(db_path):
                self.auth_users_exist = True
                self.auth_error = "A user already exists. Please sign in."
                return

            if self._setup_password != self._setup_password_confirm:
                self.auth_error = "Passwords do not match."
                return

            try:
                user = create_initial_user(db_path, self.setup_username, self._setup_password)
            except ValueError as exc:
                self.auth_error = str(exc)
                return

            token = create_session(db_path, user.id)
            self.auth_token = token
            self.current_user = user.username
            self.current_user_is_admin = user.is_admin
            self.auth_users_exist = True
            self.auth_error = ""
            self._setup_password = ""
            self._setup_password_confirm = ""
            self.refresh_user_list()

            return self._post_auth_success_events()
        except Exception as exc:
            logger.exception("Authentication failed during initial user setup: %s", exc)
            self.auth_error = "Authentication failed to initialize; check server logs."
            return

    def _on_load_impl(self):
        self._clear_auth_feedback()
        self.auth_ready = True
        self.auth_error = ""

        try:
            db_path = get_config().app.auth_db_path
            init_auth_db(db_path)

            self.auth_users_exist = has_users(db_path)

            if not self.auth_users_exist:
                self.current_user = ""
                self.current_user_is_admin = False
                self.auth_token = ""
                return

            session_user = get_session_user(db_path, self.auth_token)
            if session_user is None:
                self.current_user = ""
                self.current_user_is_admin = False
                self.auth_token = ""
                return

            if not has_admin_users(db_path):
                session_user = promote_user_to_admin(db_path, session_user.username)

            self.current_user = session_user.username
            self.current_user_is_admin = session_user.is_admin
            self.refresh_user_list()

            return self._post_auth_success_events()
        except Exception as exc:
            self.auth_users_exist = True
            self.current_user = ""
            self.current_user_is_admin = False
            self.auth_token = ""
            logger.exception("Authentication startup failed: %s", exc)
            self.auth_error = "Authentication failed to initialize; check server logs."
            return

    def _clear_auth_feedback(self) -> None:
        self.auth_error = ""
        self.account_form_error = ""
        self.admin_form_error = ""
        self.current_password_error = ""
        self.new_password_error = ""
        self.new_password_confirm_error = ""
        self.new_user_username_error = ""
        self.new_user_password_error = ""
        self.new_user_password_confirm_error = ""

    @rx.event
    def set_login_username(self, value: str):
        self.login_username = value
        self.auth_error = ""

    @rx.event
    def set_login_password(self, value: str):
        self._login_password = value
        self.auth_error = ""

    @rx.event
    def set_setup_username(self, value: str):
        self.setup_username = value
        self.auth_error = ""

    @rx.event
    def set_setup_password(self, value: str):
        self._setup_password = value
        self.auth_error = ""

    @rx.event
    def set_setup_password_confirm(self, value: str):
        self._setup_password_confirm = value
        self.auth_error = ""

    @rx.event
    def set_new_user_username(self, value: str):
        self.new_user_username = value
        self.new_user_username_error = ""
        self.admin_form_error = ""

    @rx.event
    def set_new_user_password(self, value: str):
        self._new_user_password = value
        self.new_user_password_error = ""
        self.admin_form_error = ""

    @rx.event
    def set_new_user_password_confirm(self, value: str):
        self._new_user_password_confirm = value
        self.new_user_password_confirm_error = ""
        self.admin_form_error = ""

    @rx.event
    def set_new_user_is_admin(self, value: bool):
        self.new_user_is_admin = bool(value)
        self.admin_form_error = ""

    @rx.event
    def set_current_password(self, value: str):
        self._current_password = value
        self.current_password_error = ""
        self.account_form_error = ""

    @rx.event
    def set_new_password(self, value: str):
        self._new_password = value
        self.new_password_error = ""
        self.account_form_error = ""

    @rx.event
    def set_new_password_confirm(self, value: str):
        self._new_password_confirm = value
        self.new_password_confirm_error = ""
        self.account_form_error = ""

    @rx.event
    def refresh_user_list(self):
        if not self.current_user or not self.current_user_is_admin:
            self.user_list = []
            return

        db_path = get_config().app.auth_db_path
        self.user_list = list_users_with_roles(db_path)

    @rx.event
    def login(self):
        return self._login_impl()

    @rx.event
    def logout(self):
        db_path = get_config().app.auth_db_path
        invalidate_session(db_path, self.auth_token)

        self.auth_token = ""
        self.current_user = ""
        self.current_user_is_admin = False
        self._login_password = ""
        self.user_list = []
        self._current_password = ""
        self._new_password = ""
        self._new_password_confirm = ""
        self._new_user_password = ""
        self._new_user_password_confirm = ""
        self._setup_password = ""
        self._setup_password_confirm = ""
        self._clear_auth_feedback()

        if hasattr(self, "current_page"):
            self.current_page = "today"
        if hasattr(self, "inverter_poll_generation"):
            self.inverter_poll_generation += 1

    @rx.event
    def create_initial_user(self):
        return self._create_initial_user_impl()

    @rx.event
    def create_managed_user(self):
        self.new_user_username_error = ""
        self.new_user_password_error = ""
        self.new_user_password_confirm_error = ""
        self.admin_form_error = ""

        if not self.current_user or not self.current_user_is_admin:
            self.admin_form_error = "Only administrators can create users."
            return

        username = self.new_user_username.strip()
        has_error = False
        if len(username) < 3:
            self.new_user_username_error = "Username must be at least 3 characters."
            has_error = True
        elif len(username) > 64:
            self.new_user_username_error = "Username must be 64 characters or fewer."
            has_error = True

        password_error = validate_password_strength(self._new_user_password)
        if password_error is not None:
            self.new_user_password_error = password_error
            has_error = True

        if self._new_user_password != self._new_user_password_confirm:
            self.new_user_password_confirm_error = "Passwords do not match."
            has_error = True

        if has_error:
            return

        db_path = get_config().app.auth_db_path
        try:
            create_user_as_admin(
                db_path,
                self.current_user,
                self.new_user_username,
                self._new_user_password,
                is_admin=self.new_user_is_admin,
            )
            self.new_user_username = ""
            self._new_user_password = ""
            self._new_user_password_confirm = ""
            self.new_user_is_admin = False
            self.user_list = list_users_with_roles(db_path)
            return rx.toast.success(
                "User created.",
                duration=4000,
                close_button=True,
            )
        except ValueError as exc:
            message = str(exc)
            if "username" in message.lower():
                self.new_user_username_error = message
            else:
                self.admin_form_error = message

    @rx.event
    def delete_managed_user(self, username: str):
        if not self.current_user or not self.current_user_is_admin:
            self.admin_form_error = "Only administrators can delete users."
            return

        if username == self.current_user:
            self.admin_form_error = "You cannot delete your own user."
            return rx.toast.warning(
                "You cannot delete your own user.",
                duration=4000,
                close_button=True,
            )

        db_path = get_config().app.auth_db_path
        try:
            delete_user_as_admin(db_path, self.current_user, username)
            self.admin_form_error = ""
            self.user_list = list_users_with_roles(db_path)
            return rx.toast.success(
                f"Deleted user '{username}'.",
                duration=4000,
                close_button=True,
            )
        except ValueError as exc:
            self.admin_form_error = str(exc)

    @rx.event
    def set_managed_user_admin_role(self, username: str, is_admin: bool):
        if not self.current_user or not self.current_user_is_admin:
            self.admin_form_error = "Only administrators can change user roles."
            return

        if username == self.current_user:
            self.admin_form_error = "You cannot change your own role."
            return rx.toast.warning(
                "You cannot change your own role.",
                duration=4000,
                close_button=True,
            )

        db_path = get_config().app.auth_db_path
        try:
            updated = set_user_admin_role_as_admin(
                db_path,
                self.current_user,
                username,
                is_admin=is_admin,
            )
            self.admin_form_error = ""
            self.user_list = list_users_with_roles(db_path)
            action = "Promoted" if updated.is_admin else "Demoted"
            return rx.toast.success(
                f"{action} '{updated.username}'.",
                duration=4000,
                close_button=True,
            )
        except ValueError as exc:
            self.admin_form_error = str(exc)

    @rx.event
    def update_my_password(self):
        self.current_password_error = ""
        self.new_password_error = ""
        self.new_password_confirm_error = ""
        self.account_form_error = ""

        if not self.current_user:
            self.account_form_error = "You are not signed in."
            return

        has_error = False
        if not self._current_password:
            self.current_password_error = "Current password is required."
            has_error = True

        password_error = validate_password_strength(self._new_password)
        if password_error is not None:
            self.new_password_error = password_error
            has_error = True

        if self._new_password != self._new_password_confirm:
            self.new_password_confirm_error = "Passwords do not match."
            has_error = True

        if has_error:
            return

        db_path = get_config().app.auth_db_path
        try:
            change_password(db_path, self.current_user, self._current_password, self._new_password)
            self._current_password = ""
            self._new_password = ""
            self._new_password_confirm = ""
            return rx.toast.success(
                "Password updated.",
                duration=4000,
                close_button=True,
            )
        except ValueError as exc:
            message = str(exc)
            if "current password" in message.lower():
                self.current_password_error = message
            else:
                self.account_form_error = message

    @rx.event
    def on_load(self):
        return self._on_load_impl()
