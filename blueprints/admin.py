"""Кабинет администратора: глобальная сводка, методологи, фрод-монитор.

Все эндпоинты — строго role_required('admin').
"""
from datetime import date, datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from blueprints.auth import role_required
from constants import CHART_PALETTE, ROLE_ADMIN, ROLE_METHODOLOGIST
from extensions import db
from models import ClientOrg, User
from services.analytics import methodologist_summary, top_clients_by_spend
from services.fraud import daily_hours_matrix, entries_for_day, today_totals

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


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


# --------------------------------------------------------------------------- #
# Глобальная сводка по методологам
# --------------------------------------------------------------------------- #
@admin_bp.route("/")
@role_required(ROLE_ADMIN)
def dashboard():
    year, month = _month_from_request()

    summary = methodologist_summary(year, month)
    active_rows = [r for r in summary if r["is_active"]]

    method_chart = {
        "labels": [r["name"] for r in active_rows],
        "data": [float(r["total_consumed"]) for r in active_rows],
        "colors": [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(active_rows))],
    }
    top_clients = top_clients_by_spend(year, month, limit=10)
    client_chart = {
        "labels": [c["name"] for c in top_clients],
        "data": [float(c["hours"]) for c in top_clients],
        "colors": [CHART_PALETTE[i % len(CHART_PALETTE)] for i in range(len(top_clients))],
    }

    prev_y, prev_m = _shift_month(year, month, -1)
    next_y, next_m = _shift_month(year, month, 1)

    return render_template(
        "admin/dashboard.html",
        year=year,
        month=month,
        summary=summary,
        method_chart=method_chart,
        client_chart=client_chart,
        has_client_data=bool(top_clients),
        has_method_data=any(r["total_consumed"] > 0 for r in active_rows),
        prev_month={"year": prev_y, "month": prev_m},
        next_month={"year": next_y, "month": next_m},
    )


# --------------------------------------------------------------------------- #
# Управление учётками методологов
# --------------------------------------------------------------------------- #
@admin_bp.route("/methodologists", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def methodologists():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        if not full_name or not email or not password:
            flash("ФИО, email и пароль обязательны.", "error")
        elif User.query.filter_by(login=email).first() is not None:
            flash("Пользователь с таким email уже существует.", "error")
        else:
            # Логин = email: отдельного логина у методологов нет.
            m = User(
                role=ROLE_METHODOLOGIST,
                full_name=full_name,
                login=email,
                email=email,
                is_active=True,
            )
            m.set_password(password)
            db.session.add(m)
            db.session.commit()
            flash(f"Методолог {full_name} создан.", "info")
            return redirect(url_for("admin.methodologists"))

    methods = (
        User.query.filter_by(role=ROLE_METHODOLOGIST)
        .order_by(User.is_active.desc(), User.full_name)
        .all()
    )
    client_counts = {
        m.id: ClientOrg.query.filter_by(methodologist_id=m.id, is_active=True).count()
        for m in methods
    }
    return render_template(
        "admin/methodologists.html",
        methods=methods,
        client_counts=client_counts,
    )


@admin_bp.route("/methodologists/<int:user_id>/toggle-active", methods=["POST"])
@role_required(ROLE_ADMIN)
def toggle_methodologist(user_id):
    m = db.session.get(User, user_id)
    if m is None or m.role != ROLE_METHODOLOGIST:
        abort(404)

    if m.is_active:
        active_clients = ClientOrg.query.filter_by(
            methodologist_id=m.id, is_active=True
        ).count()
        if active_clients > 0:
            flash(
                "Нельзя деактивировать методолога с активными клиентами — "
                "сначала переназначьте клиентов.",
                "error",
            )
            return redirect(url_for("admin.methodologists"))
        m.is_active = False
        flash("Методолог деактивирован.", "info")
    else:
        m.is_active = True
        flash("Методолог активирован.", "info")
    db.session.commit()
    return redirect(url_for("admin.methodologists"))


@admin_bp.route("/methodologists/<int:user_id>/reset-password", methods=["POST"])
@role_required(ROLE_ADMIN)
def reset_password(user_id):
    m = db.session.get(User, user_id)
    if m is None or m.role != ROLE_METHODOLOGIST:
        abort(404)
    new_password = request.form.get("password") or ""
    if len(new_password) < 4:
        flash("Пароль слишком короткий (минимум 4 символа).", "error")
        return redirect(url_for("admin.methodologists"))
    m.set_password(new_password)
    db.session.commit()
    flash(f"Пароль методолога {m.full_name} обновлён.", "info")
    return redirect(url_for("admin.methodologists"))


# --------------------------------------------------------------------------- #
# Управление администраторами
# --------------------------------------------------------------------------- #
@admin_bp.route("/admins", methods=["GET", "POST"])
@role_required(ROLE_ADMIN)
def admins():
    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip()
        password = request.form.get("password") or ""

        if not full_name or not email or not password:
            flash("ФИО, email и пароль обязательны.", "error")
        elif User.query.filter_by(login=email).first() is not None:
            flash("Пользователь с таким email уже существует.", "error")
        else:
            # Логин = email.
            a = User(
                role=ROLE_ADMIN,
                full_name=full_name,
                login=email,
                email=email,
                is_active=True,
            )
            a.set_password(password)
            db.session.add(a)
            db.session.commit()
            flash(f"Администратор {full_name} создан.", "info")
            return redirect(url_for("admin.admins"))

    admin_users = (
        User.query.filter_by(role=ROLE_ADMIN)
        .order_by(User.is_active.desc(), User.full_name)
        .all()
    )
    active_admins = sum(1 for a in admin_users if a.is_active)
    return render_template(
        "admin/admins.html",
        admins=admin_users,
        active_admins=active_admins,
    )


@admin_bp.route("/admins/<int:user_id>/toggle-active", methods=["POST"])
@role_required(ROLE_ADMIN)
def toggle_admin(user_id):
    a = db.session.get(User, user_id)
    if a is None or a.role != ROLE_ADMIN:
        abort(404)

    if a.is_active:
        if a.id == current_user.id:
            flash("Нельзя деактивировать самого себя.", "error")
            return redirect(url_for("admin.admins"))
        active_admins = User.query.filter_by(role=ROLE_ADMIN, is_active=True).count()
        if active_admins <= 1:
            flash("В системе должен остаться хотя бы один активный админ.", "error")
            return redirect(url_for("admin.admins"))
        a.is_active = False
        flash("Администратор деактивирован.", "info")
    else:
        a.is_active = True
        flash("Администратор активирован.", "info")
    db.session.commit()
    return redirect(url_for("admin.admins"))


@admin_bp.route("/admins/<int:user_id>/reset-password", methods=["POST"])
@role_required(ROLE_ADMIN)
def reset_admin_password(user_id):
    a = db.session.get(User, user_id)
    if a is None or a.role != ROLE_ADMIN:
        abort(404)
    new_password = request.form.get("password") or ""
    if len(new_password) < 4:
        flash("Пароль слишком короткий (минимум 4 символа).", "error")
        return redirect(url_for("admin.admins"))
    a.set_password(new_password)
    db.session.commit()
    flash(f"Пароль администратора {a.full_name} обновлён.", "info")
    return redirect(url_for("admin.admins"))


# --------------------------------------------------------------------------- #
# Фрод-монитор
# --------------------------------------------------------------------------- #
@admin_bp.route("/fraud")
@role_required(ROLE_ADMIN)
def fraud():
    threshold = current_app.config.get("FRAUD_DAILY_HOURS_THRESHOLD", 8)
    days = request.args.get("days", type=int) or 14
    days = max(7, min(days, 31))

    matrix = daily_hours_matrix(days=days)
    totals = today_totals()

    return render_template(
        "admin/fraud.html",
        matrix=matrix,
        today_totals=totals,
        threshold=threshold,
        days=days,
        today=date.today(),
    )


@admin_bp.route("/fraud/entries")
@role_required(ROLE_ADMIN)
def fraud_entries():
    mid = request.args.get("methodologist_id", type=int)
    day_raw = request.args.get("date")
    if not mid or not day_raw:
        abort(400)
    try:
        day = datetime.strptime(day_raw, "%Y-%m-%d").date()
    except ValueError:
        abort(400)

    m = db.session.get(User, mid)
    if m is None:
        abort(404)

    threshold = current_app.config.get("FRAUD_DAILY_HOURS_THRESHOLD", 8)
    rows = entries_for_day(mid, day)
    total = sum((r["entry"].hours for r in rows), __import__("decimal").Decimal("0"))

    return render_template(
        "admin/fraud_entries.html",
        methodologist=m,
        day=day,
        rows=rows,
        total=total,
        threshold=threshold,
    )
