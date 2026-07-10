"""Кабинет администратора: дашборд нагрузки по всем клиентам (охват — все методологи)."""
from datetime import date

from flask import Blueprint, render_template, request

from blueprints.auth import role_required
from blueprints.methodologist import build_workload_context
from constants import ROLE_ADMIN
from models import ClientOrg

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


@admin_bp.route("/")
@role_required(ROLE_ADMIN)
def dashboard():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    clients = ClientOrg.query.filter_by(is_active=True).order_by(ClientOrg.name).all()
    work, by_client_chart = build_workload_context(clients, year, month)

    return render_template(
        "admin/dashboard.html",
        work=work,
        by_client_chart=by_client_chart,
        year=year,
        month=month,
    )
