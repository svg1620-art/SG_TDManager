"""Управление организациями-клиентами, их сотрудниками и месячными бюджетами.

Доступ: методолог (только свои клиенты) и админ (все клиенты).
"""
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from blueprints.auth import role_required
from constants import (
    NOTIF_CLIENT_ASSIGNED,
    NOTIF_CLIENT_TRANSFERRED,
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_METHODOLOGIST,
)
from extensions import db
from models import (
    BudgetAdjustment,
    ClientOrg,
    ClientReassignment,
    MonthlyBudget,
    User,
)
from services.budgets import (
    add_hours,
    base_limit,
    create_month_budgets_for_active_clients,
    effective_limit,
    sum_adjustments,
)
from services.notifications import notify

clients_bp = Blueprint("clients", __name__, url_prefix="/clients")

CONTRACT_MONTHS_CHOICES = (3, 6, 12)


# --------------------------------------------------------------------------- #
# Хелперы
# --------------------------------------------------------------------------- #
def _load_client_or_403(client_id) -> ClientOrg:
    """Загрузить клиента с проверкой владения: методолог видит только своих."""
    org = db.session.get(ClientOrg, client_id)
    if org is None:
        abort(404)
    if current_user.is_methodologist and org.methodologist_id != current_user.id:
        abort(403)
    return org


def _add_months(d: date, months: int) -> date:
    """Прибавить месяцы к дате с корректным переносом года и обрезкой дня."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _parse_decimal(raw, field_label):
    """Разобрать строку в Decimal или бросить ValueError с понятным сообщением."""
    if raw is None or str(raw).strip() == "":
        raise ValueError(f"Поле «{field_label}» обязательно.")
    try:
        return Decimal(str(raw).replace(",", ".").strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"Поле «{field_label}» должно быть числом.")


def _parse_date(raw):
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ValueError("Некорректная дата.")


def _budget_rows(org: ClientOrg):
    """Собрать строки таблицы лимитов по месяцам для профиля клиента."""
    budgets = (
        MonthlyBudget.query.filter_by(client_id=org.id)
        .order_by(MonthlyBudget.year.desc(), MonthlyBudget.month.desc())
        .all()
    )
    today = date.today()
    rows = []
    for b in budgets:
        adj = sum_adjustments(org.id, b.year, b.month)
        rows.append(
            {
                "year": b.year,
                "month": b.month,
                "base": Decimal(str(b.base_limit_hours)),
                "adjustments": adj,
                "effective": Decimal(str(b.base_limit_hours)) + adj,
                "is_current": (b.year == today.year and b.month == today.month),
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# Список клиентов
# --------------------------------------------------------------------------- #
@clients_bp.route("/")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def list_clients():
    show_archived = request.args.get("archived") == "1"

    query = ClientOrg.query
    if current_user.is_methodologist:
        query = query.filter_by(methodologist_id=current_user.id)
    query = query.filter_by(is_active=not show_archived)
    orgs = query.order_by(ClientOrg.name).all()

    # Счётчик сотрудников по каждому клиенту.
    employee_counts = {
        org.id: User.query.filter_by(
            client_id=org.id, role=ROLE_CLIENT, is_active=True
        ).count()
        for org in orgs
    }

    return render_template(
        "clients/list.html",
        orgs=orgs,
        employee_counts=employee_counts,
        show_archived=show_archived,
    )


# --------------------------------------------------------------------------- #
# Создание / редактирование клиента
# --------------------------------------------------------------------------- #
@clients_bp.route("/new", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def new_client():
    methodologists = _methodologists_for_select()

    if request.method == "POST":
        try:
            org = _apply_client_form(ClientOrg(), methodologists)
            db.session.add(org)
            db.session.commit()
            flash("Клиент создан.", "info")
            return redirect(url_for("clients.client_detail", client_id=org.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")

    return render_template(
        "clients/form.html",
        org=None,
        methodologists=methodologists,
        contract_choices=CONTRACT_MONTHS_CHOICES,
    )


@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def edit_client(client_id):
    org = _load_client_or_403(client_id)
    methodologists = _methodologists_for_select()

    if request.method == "POST":
        try:
            _apply_client_form(org, methodologists)
            db.session.commit()
            flash("Данные клиента обновлены.", "info")
            return redirect(url_for("clients.client_detail", client_id=org.id))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), "error")

    return render_template(
        "clients/form.html",
        org=org,
        methodologists=methodologists,
        contract_choices=CONTRACT_MONTHS_CHOICES,
    )


def _methodologists_for_select():
    """Список методологов для выбора админом (методологу не показываем)."""
    if not current_user.is_admin:
        return []
    return (
        User.query.filter_by(role=ROLE_METHODOLOGIST, is_active=True)
        .order_by(User.full_name)
        .all()
    )


def _apply_client_form(org: ClientOrg, methodologists) -> ClientOrg:
    """Заполнить поля клиента из формы. Бросает ValueError на невалидных данных."""
    name = (request.form.get("name") or "").strip()
    if not name:
        raise ValueError("Название организации обязательно.")

    default_hours = _parse_decimal(
        request.form.get("default_monthly_hours"), "Лимит по умолчанию"
    )
    if default_hours < 0:
        raise ValueError("Лимит по умолчанию не может быть отрицательным.")

    contract_months = request.form.get("contract_months")
    contract_months = int(contract_months) if contract_months else None
    if contract_months is not None and contract_months not in CONTRACT_MONTHS_CHOICES:
        raise ValueError("Срок контракта должен быть 3, 6 или 12 месяцев.")

    contract_start = _parse_date(request.form.get("contract_start"))
    contract_end = _parse_date(request.form.get("contract_end"))
    # Если конец не задан вручную — считаем от старта + срок.
    if contract_end is None and contract_start and contract_months:
        contract_end = _add_months(contract_start, contract_months)

    # Владелец-методолог.
    if current_user.is_methodologist:
        methodologist_id = current_user.id  # методолог заводит клиента на себя
    else:
        raw_mid = request.form.get("methodologist_id")
        methodologist_id = int(raw_mid) if raw_mid else None
        if methodologist_id is not None and methodologist_id not in {
            m.id for m in methodologists
        }:
            raise ValueError("Выбран некорректный методолог.")

    org.name = name
    org.default_monthly_hours = default_hours
    org.contract_months = contract_months
    org.contract_start = contract_start
    org.contract_end = contract_end
    org.telegram_chat_id = (request.form.get("telegram_chat_id") or "").strip() or None
    org.notes = (request.form.get("notes") or "").strip() or None
    org.methodologist_id = methodologist_id
    # is_active управляется отдельными действиями (деактивация), при создании — True.
    if org.id is None:
        org.is_active = True
    return org


# --------------------------------------------------------------------------- #
# Telegram-пульс: определение chat_id, тест, ручной прогон
# --------------------------------------------------------------------------- #
@clients_bp.route("/<int:client_id>/telegram/chats")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def telegram_chats(client_id):
    org = _load_client_or_403(client_id)
    from services.telegram import get_updates

    result = get_updates()
    return render_template("clients/telegram_chats.html", org=org, result=result)


@clients_bp.route("/<int:client_id>/telegram/set", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def telegram_set(client_id):
    org = _load_client_or_403(client_id)
    chat_id = (request.form.get("chat_id") or "").strip()
    org.telegram_chat_id = chat_id or None
    db.session.commit()
    flash(
        f"chat_id сохранён: {chat_id}" if chat_id else "chat_id очищен.",
        "info",
    )
    return redirect(url_for("clients.client_detail", client_id=org.id))


@clients_bp.route("/<int:client_id>/telegram/test", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def telegram_test(client_id):
    org = _load_client_or_403(client_id)
    if not org.telegram_chat_id:
        flash("Сначала укажите telegram_chat_id.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))
    from services.telegram import escape, send_message

    ok = send_message(
        org.telegram_chat_id,
        f"Пульс подключён ✅\n<b>{escape(org.name)}</b>",
    )
    flash(
        "Тестовое сообщение отправлено." if ok else "Не удалось отправить — проверьте токен и chat_id.",
        "info" if ok else "error",
    )
    return redirect(url_for("clients.client_detail", client_id=org.id))


@clients_bp.route("/<int:client_id>/telegram/pulse", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def telegram_pulse_now(client_id):
    org = _load_client_or_403(client_id)
    from services.pulse import run_pulse

    stats = run_pulse(client_id=org.id)
    if stats["sent"]:
        flash("Пульс отправлен.", "info")
    elif not org.telegram_chat_id:
        flash("У клиента не задан telegram_chat_id.", "error")
    elif stats["skipped"]:
        flash("Пульс пропущен: за сегодня нет активности (пустой пульс не шлём).", "info")
    else:
        flash("Не удалось отправить пульс — проверьте токен и chat_id.", "error")
    return redirect(url_for("clients.client_detail", client_id=org.id))


@clients_bp.route("/<int:client_id>/delete", methods=["POST"])
@role_required(ROLE_ADMIN)
def delete_client_route(client_id):
    org = db.session.get(ClientOrg, client_id)
    if org is None:
        abort(404)
    name = org.name
    from services.deletion import delete_client

    delete_client(client_id)
    flash(f"Компания «{name}» и все её данные удалены.", "info")
    return redirect(url_for("clients.list_clients"))


@clients_bp.route("/<int:client_id>/toggle-active", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def toggle_active(client_id):
    org = _load_client_or_403(client_id)
    org.is_active = not org.is_active
    db.session.commit()
    flash(
        "Клиент активирован." if org.is_active else "Клиент перенесён в архив.",
        "info",
    )
    return redirect(url_for("clients.client_detail", client_id=org.id))


# --------------------------------------------------------------------------- #
# Профиль клиента
# --------------------------------------------------------------------------- #
@clients_bp.route("/<int:client_id>")
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def client_detail(client_id):
    org = _load_client_or_403(client_id)
    today = date.today()

    employees = (
        User.query.filter_by(client_id=org.id, role=ROLE_CLIENT)
        .order_by(User.is_active.desc(), User.full_name)
        .all()
    )

    budget_rows = _budget_rows(org)

    adjustments = (
        BudgetAdjustment.query.filter_by(client_id=org.id)
        .order_by(BudgetAdjustment.created_at.desc())
        .limit(100)
        .all()
    )
    # Имена авторов добавлений (для аудита).
    author_ids = {a.created_by for a in adjustments if a.created_by}
    authors = {
        u.id: u.full_name
        for u in User.query.filter(User.id.in_(author_ids)).all()
    } if author_ids else {}

    # Переназначение (только админ): список активных методологов + история передач.
    active_methodologists = []
    reassignments = []
    if current_user.is_admin:
        active_methodologists = (
            User.query.filter_by(role=ROLE_METHODOLOGIST, is_active=True)
            .order_by(User.full_name)
            .all()
        )
        reassignments = (
            ClientReassignment.query.filter_by(client_id=org.id)
            .order_by(ClientReassignment.created_at.desc())
            .all()
        )

    return render_template(
        "clients/detail.html",
        org=org,
        employees=employees,
        budget_rows=budget_rows,
        adjustments=adjustments,
        authors=authors,
        current_year=today.year,
        current_month=today.month,
        current_effective=effective_limit(org.id, today.year, today.month),
        current_base=base_limit(org.id, today.year, today.month),
        current_adjustments=sum_adjustments(org.id, today.year, today.month),
        active_methodologists=active_methodologists,
        reassignments=reassignments,
    )


@clients_bp.route("/<int:client_id>/reassign", methods=["POST"])
@role_required(ROLE_ADMIN)
def reassign(client_id):
    org = db.session.get(ClientOrg, client_id)
    if org is None:
        abort(404)

    try:
        new_mid = int(request.form.get("methodologist_id"))
    except (TypeError, ValueError):
        flash("Выберите методолога.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Укажите причину передачи.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    new_m = db.session.get(User, new_mid)
    if new_m is None or new_m.role != ROLE_METHODOLOGIST or not new_m.is_active:
        flash("Некорректный методолог.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    old_mid = org.methodologist_id
    if old_mid == new_mid:
        flash("Клиент уже закреплён за этим методологом.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    # Меняем владельца — задачи переезжают автоматически (видимость по methodologist_id).
    # time_entries НЕ трогаем: историческая атрибуция исполнителя сохраняется.
    org.methodologist_id = new_mid
    db.session.add(
        ClientReassignment(
            client_id=org.id,
            from_methodologist_id=old_mid,
            to_methodologist_id=new_mid,
            changed_by=current_user.id,
            reason=reason,
        )
    )
    db.session.commit()

    notify(new_mid, NOTIF_CLIENT_ASSIGNED, f"Вам передан клиент «{org.name}».")
    if old_mid:
        notify(
            old_mid,
            NOTIF_CLIENT_TRANSFERRED,
            f"Клиент «{org.name}» передан другому методологу.",
        )

    flash(f"Клиент передан методологу {new_m.full_name}.", "info")
    return redirect(url_for("clients.client_detail", client_id=org.id))


# --------------------------------------------------------------------------- #
# Сотрудники
# --------------------------------------------------------------------------- #
@clients_bp.route("/<int:client_id>/employees", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def add_employee(client_id):
    org = _load_client_or_403(client_id)

    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    if not full_name or not email or not password:
        flash("ФИО, email и пароль обязательны.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    if User.query.filter_by(login=email).first() is not None:
        flash("Пользователь с таким email уже существует.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    # Логин = email: отдельного логина у сотрудников нет.
    employee = User(
        role=ROLE_CLIENT,
        full_name=full_name,
        login=email,
        email=email,
        client_id=org.id,
        is_active=True,
    )
    employee.set_password(password)
    db.session.add(employee)
    db.session.commit()
    flash(f"Сотрудник {full_name} добавлен.", "info")
    return redirect(url_for("clients.client_detail", client_id=org.id))


@clients_bp.route("/employees/<int:user_id>/edit", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def edit_employee(user_id):
    employee = db.session.get(User, user_id)
    if employee is None or employee.role != ROLE_CLIENT or employee.client_id is None:
        abort(404)
    # Проверка владения через организацию сотрудника.
    _load_client_or_403(employee.client_id)

    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").strip()
    password = request.form.get("password") or ""

    if not full_name or not email:
        flash("ФИО и email обязательны.", "error")
        return redirect(url_for("clients.client_detail", client_id=employee.client_id))

    # Email = логин: проверяем уникальность, исключая самого сотрудника.
    other = User.query.filter_by(login=email).first()
    if other is not None and other.id != employee.id:
        flash("Пользователь с таким email уже существует.", "error")
        return redirect(url_for("clients.client_detail", client_id=employee.client_id))

    employee.full_name = full_name
    employee.email = email
    employee.login = email
    if password:
        employee.set_password(password)
    db.session.commit()
    flash(f"Данные сотрудника {full_name} обновлены.", "info")
    return redirect(url_for("clients.client_detail", client_id=employee.client_id))


@clients_bp.route("/employees/<int:user_id>/toggle-active", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def toggle_employee(user_id):
    employee = db.session.get(User, user_id)
    if employee is None or employee.role != ROLE_CLIENT or employee.client_id is None:
        abort(404)
    # Проверка владения через организацию сотрудника.
    _load_client_or_403(employee.client_id)

    employee.is_active = not employee.is_active
    db.session.commit()
    flash(
        "Сотрудник активирован." if employee.is_active else "Сотрудник деактивирован.",
        "info",
    )
    return redirect(url_for("clients.client_detail", client_id=employee.client_id))


# --------------------------------------------------------------------------- #
# Месячные лимиты и добавление часов
# --------------------------------------------------------------------------- #
@clients_bp.route("/<int:client_id>/budget", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def set_budget(client_id):
    org = _load_client_or_403(client_id)
    try:
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        if not (1 <= month <= 12):
            raise ValueError("Месяц должен быть от 1 до 12.")
        hours = _parse_decimal(request.form.get("base_limit_hours"), "Лимит часов")
        if hours < 0:
            raise ValueError("Лимит часов не может быть отрицательным.")
    except (TypeError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else "Некорректные данные.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    budget = MonthlyBudget.query.filter_by(
        client_id=org.id, year=year, month=month
    ).first()
    if budget is None:
        budget = MonthlyBudget(
            client_id=org.id,
            year=year,
            month=month,
            base_limit_hours=hours,
            created_by=current_user.id,
        )
        db.session.add(budget)
    else:
        budget.base_limit_hours = hours
    db.session.commit()
    flash(f"Лимит на {month:02d}.{year} сохранён.", "info")
    return redirect(url_for("clients.client_detail", client_id=org.id))


@clients_bp.route("/<int:client_id>/adjustment", methods=["POST"])
@role_required(ROLE_ADMIN, ROLE_METHODOLOGIST)
def add_adjustment(client_id):
    org = _load_client_or_403(client_id)
    try:
        year = int(request.form.get("year"))
        month = int(request.form.get("month"))
        if not (1 <= month <= 12):
            raise ValueError("Месяц должен быть от 1 до 12.")
        delta = _parse_decimal(request.form.get("delta_hours"), "Часы")
        if delta == 0:
            raise ValueError("Количество часов не может быть нулём.")
        reason = (request.form.get("reason") or "").strip()
        if not reason:
            raise ValueError("Укажите причину добавления часов.")
    except (TypeError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, ValueError) else "Некорректные данные.", "error")
        return redirect(url_for("clients.client_detail", client_id=org.id))

    add_hours(org.id, year, month, delta, reason, current_user.id)
    flash("Часы добавлены и записаны в аудит.", "info")
    return redirect(url_for("clients.client_detail", client_id=org.id))


# --------------------------------------------------------------------------- #
# Ручной пересчёт бюджетов текущего месяца (админ)
# --------------------------------------------------------------------------- #
@clients_bp.route("/recalc-budgets", methods=["POST"])
@role_required(ROLE_ADMIN)
def recalc_budgets():
    today = date.today()
    created = create_month_budgets_for_active_clients(
        today.year, today.month, created_by=current_user.id
    )
    flash(
        f"Пересчёт завершён: создано новых бюджетов — {created}.",
        "info",
    )
    return redirect(url_for("clients.list_clients"))
