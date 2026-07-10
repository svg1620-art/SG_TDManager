"""Рабочее место методолога: дашборд нагрузки по своим клиентам."""
from datetime import date

from flask import Blueprint, render_template, request
from flask_login import current_user

from blueprints.auth import role_required
from constants import CHART_PALETTE, ROLE_METHODOLOGIST
from models import ClientOrg
from services.analytics import workload_summary

methodologist_bp = Blueprint("methodologist", __name__, url_prefix="/methodologist")


def build_workload_context(clients, year, month):
    """Собрать контекст дашборда нагрузки + данные для донат-графика по клиентам."""
    work = workload_summary(clients, year, month)
    hbc = work["hours_by_client"]
    by_client_chart = {
        "labels": [r["name"] for r in hbc],
        "data": [float(r["hours"]) for r in hbc],
        "colors": [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(hbc))],
    }
    return work, by_client_chart


@methodologist_bp.route("/")
@role_required(ROLE_METHODOLOGIST)
def dashboard():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month

    clients = (
        ClientOrg.query.filter_by(methodologist_id=current_user.id, is_active=True)
        .order_by(ClientOrg.name)
        .all()
    )
    work, by_client_chart = build_workload_context(clients, year, month)

    return render_template(
        "methodologist/dashboard.html",
        work=work,
        by_client_chart=by_client_chart,
        year=year,
        month=month,
    )
