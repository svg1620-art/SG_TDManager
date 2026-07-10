"""Аутентификация: login/logout, редирект по роли, декоратор проверки роли."""
from functools import wraps

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from constants import ROLE_ADMIN, ROLE_CLIENT, ROLE_METHODOLOGIST
from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__)


def dashboard_endpoint_for(user) -> str:
    """Возвращает endpoint дашборда по роли пользователя."""
    if user.is_admin:
        return "admin.dashboard"
    if user.is_methodologist:
        return "methodologist.dashboard"
    return "client.dashboard"


def role_required(*roles):
    """Декоратор: доступ только пользователям с одной из указанных ролей, иначе 403."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(dashboard_endpoint_for(current_user)))

    if request.method == "POST":
        login_value = (request.form.get("login") or "").strip()
        password = request.form.get("password") or ""

        user = User.query.filter_by(login=login_value).first()
        if user is None or not user.check_password(password):
            flash("Неверный логин или пароль.", "error")
            return render_template("login.html"), 401
        if not user.is_active:
            flash("Учётная запись отключена.", "error")
            return render_template("login.html"), 403

        login_user(user)
        next_url = request.args.get("next")
        # Разрешаем только локальные редиректы (защита от open redirect).
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return redirect(url_for(dashboard_endpoint_for(user)))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("auth.login"))
