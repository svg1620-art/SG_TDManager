"""Дашборд администратора (заглушка Стадии 1)."""
from flask import Blueprint, render_template

from blueprints.auth import role_required
from constants import ROLE_ADMIN

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@role_required(ROLE_ADMIN)
def dashboard():
    return render_template("admin/dashboard.html")
