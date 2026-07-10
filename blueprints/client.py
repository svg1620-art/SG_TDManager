"""Дашборд клиента (заглушка Стадии 1)."""
from flask import Blueprint, render_template
from flask_login import current_user

from blueprints.auth import role_required
from constants import ROLE_CLIENT

client_bp = Blueprint("client", __name__, url_prefix="/client")


@client_bp.route("/")
@role_required(ROLE_CLIENT)
def dashboard():
    org = current_user.organization  # может быть None, шаблон это учитывает
    return render_template("client/dashboard.html", org=org)
