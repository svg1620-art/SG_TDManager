"""Дашборд методолога (заглушка Стадии 1)."""
from flask import Blueprint, render_template

from blueprints.auth import role_required
from constants import ROLE_METHODOLOGIST

methodologist_bp = Blueprint("methodologist", __name__, url_prefix="/methodologist")


@methodologist_bp.route("/")
@role_required(ROLE_METHODOLOGIST)
def dashboard():
    return render_template("methodologist/dashboard.html")
