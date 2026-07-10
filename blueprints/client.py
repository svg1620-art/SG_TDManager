"""Кабинет клиента: дашборд с графикой (Chart.js) по текущему/выбранному месяцу."""
from datetime import date

from flask import Blueprint, render_template, request
from flask_login import current_user

from blueprints.auth import role_required
from constants import (
    CHART_PALETTE,
    ROLE_CLIENT,
    STATUS_COLORS,
    STATUS_LABELS,
    WORK_TYPE_LABELS,
)
from models import ClientOrg, Task, User
from services.analytics import (
    ACTIVE_STATUSES,
    DONE_STATUSES,
    hours_by_work_type,
    status_distribution,
)
from services.budgets import consumed_hours, effective_limit

client_bp = Blueprint("client", __name__, url_prefix="/client")


def _month_from_request():
    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    if not (1 <= month <= 12):
        month = today.month
    return year, month


def _shift_month(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


@client_bp.route("/")
@role_required(ROLE_CLIENT)
def dashboard():
    org = current_user.organization
    year, month = _month_from_request()

    if org is None:
        return render_template("client/dashboard.html", org=None)

    client_ids = [org.id]

    # --- Гейдж лимита ---
    eff = effective_limit(org.id, year, month)
    cons = consumed_hours(org.id, year, month)
    remaining = eff - cons

    # --- Донат по статусам (все задачи организации) ---
    dist = status_distribution(client_ids)
    status_chart = {
        "labels": [STATUS_LABELS[s] for s, n in dist.items() if n > 0],
        "data": [n for s, n in dist.items() if n > 0],
        "colors": [STATUS_COLORS[s] for s, n in dist.items() if n > 0],
    }

    # --- Донат по типам работ (часы за месяц) ---
    hbt = hours_by_work_type(client_ids, year, month)
    nonzero_wt = [(w, h) for w, h in hbt.items() if h > 0]
    worktype_chart = {
        "labels": [WORK_TYPE_LABELS[w] for w, _ in nonzero_wt],
        "data": [float(h) for _, h in nonzero_wt],
        "colors": [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(nonzero_wt))],
    }

    # --- KPI ---
    total_tasks = sum(dist.values())
    active_tasks = sum(n for s, n in dist.items() if s in ACTIVE_STATUSES)
    done_tasks = sum(n for s, n in dist.items() if s in DONE_STATUSES)

    # --- Список задач организации ---
    tasks = (
        Task.query.filter_by(client_id=org.id)
        .order_by(Task.updated_at.desc())
        .all()
    )
    author_ids = {t.created_by for t in tasks if t.created_by}
    authors = {
        u.id: u.full_name for u in User.query.filter(User.id.in_(author_ids)).all()
    } if author_ids else {}

    prev_y, prev_m = _shift_month(year, month, -1)
    next_y, next_m = _shift_month(year, month, 1)

    return render_template(
        "client/dashboard.html",
        org=org,
        year=year,
        month=month,
        gauge={
            "effective": float(eff),
            "consumed": float(cons),
            "remaining": float(remaining),
            "over": remaining < 0,
        },
        eff=eff,
        cons=cons,
        remaining=remaining,
        status_chart=status_chart,
        worktype_chart=worktype_chart,
        kpi={"total": total_tasks, "active": active_tasks, "done": done_tasks},
        tasks=tasks,
        authors=authors,
        prev_month={"year": prev_y, "month": prev_m},
        next_month={"year": next_y, "month": next_m},
    )
