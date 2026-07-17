"""Точка входа: app factory, регистрация blueprint'ов, init БД, сид, APScheduler-заглушка."""
import logging
import os

from flask import Flask

from config import Config
from constants import (
    PRIORITY_LABELS,
    ROLE_LABELS,
    STATUS_LABELS,
    WORK_TYPE_LABELS,
)
from extensions import db, login_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ссылка на планировщик, чтобы не создавать его дважды.
_scheduler = None


def _monthly_budget_job(app) -> None:
    """1-е число: создать месячные бюджеты активным клиентам из default_monthly_hours."""
    with app.app_context():
        from datetime import date

        from services.budgets import create_month_budgets_for_active_clients

        today = date.today()
        created = create_month_budgets_for_active_clients(today.year, today.month)
        logger.info(
            "Cron месячных бюджетов: создано %s записей за %s-%02d.",
            created,
            today.year,
            today.month,
        )


def _pulse_job(app) -> None:
    """Ежедневный Telegram-пульс активным клиентам с telegram_chat_id."""
    with app.app_context():
        from services.pulse import run_pulse

        stats = run_pulse()
        logger.info("Cron пульса: %s", stats)


def _internal_digest_job(app) -> None:
    """Раз в час: если настроенный час по МСК наступил и отчёт включён — отправить.

    Час хранится в настройках (редактируется из UI), поэтому проверяем ежечасно,
    а не пересоздаём cron при каждой правке.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    with app.app_context():
        from services import settings
        from services.pulse import run_internal_digest

        if not settings.is_internal_digest_enabled():
            return
        target_hour = settings.internal_digest_hour()
        now_hour = datetime.now(ZoneInfo("Europe/Moscow")).hour
        if now_hour != target_hour:
            return
        result = run_internal_digest()
        logger.info("Cron внутреннего отчёта: %s", result)


def _init_scheduler(app) -> None:
    """Инициализирует BackgroundScheduler и регистрирует cron-задачи.

    Гвард: под gunicorn с несколькими воркерами планировщик должен стартовать один раз.
    Управляется env RUN_SCHEDULER (по умолчанию включён). Для мульти-воркерной
    конфигурации выставить RUN_SCHEDULER=0 у всех воркеров кроме одного (или
    вынести планировщик в отдельный процесс). Procfile пинит --workers 1.
    """
    global _scheduler

    if os.environ.get("RUN_SCHEDULER", "1") != "1":
        logger.info("APScheduler отключён через RUN_SCHEDULER.")
        return
    if _scheduler is not None:
        return

    # Werkzeug reloader запускает процесс дважды — планировщик только в главном.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return

    from zoneinfo import ZoneInfo

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    from services.pulse import PULSE_HOUR

    _scheduler = BackgroundScheduler(timezone="UTC")
    # 1-е число каждого месяца в 00:05 — автосоздание месячных бюджетов.
    _scheduler.add_job(
        lambda: _monthly_budget_job(app),
        CronTrigger(day=1, hour=0, minute=5),
        id="monthly_budgets",
        replace_existing=True,
    )
    # Ежедневный Telegram-пульс в PULSE_HOUR по московскому времени (день считаем по МСК).
    _scheduler.add_job(
        lambda: _pulse_job(app),
        CronTrigger(hour=PULSE_HOUR, minute=0, timezone=ZoneInfo("Europe/Moscow")),
        id="daily_pulse",
        replace_existing=True,
    )
    # Ежечасная проверка отправки общего управленческого отчёта (час — из настроек).
    _scheduler.add_job(
        lambda: _internal_digest_job(app),
        CronTrigger(minute=0, timezone=ZoneInfo("Europe/Moscow")),
        id="internal_digest",
        replace_existing=True,
    )
    # Задача AI-отчётов (Стадия 8) добавится позже.
    _scheduler.start()
    logger.info(
        "APScheduler запущен (monthly_budgets, daily_pulse, internal_digest)."
    )


def _ensure_columns() -> None:
    """Идемпотентно добавляет недостающие колонки в существующие таблицы.

    Нужно потому, что db.create_all() создаёт только отсутствующие таблицы, но не
    изменяет уже существующие (миграций в проекте нет). Диалект-независимо.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(db.engine)
    try:
        columns = {c["name"] for c in inspector.get_columns("client_orgs")}
    except Exception:  # noqa: BLE001 — таблицы ещё нет (create_all её создаст сам)
        return

    if "instant_notifications_enabled" not in columns:
        default = "true" if db.engine.dialect.name == "postgresql" else "1"
        db.session.execute(
            text(
                "ALTER TABLE client_orgs ADD COLUMN instant_notifications_enabled "
                f"BOOLEAN NOT NULL DEFAULT {default}"
            )
        )
        db.session.commit()
        logger.info("Добавлена колонка client_orgs.instant_notifications_enabled.")


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Расширения.
    db.init_app(app)
    login_manager.init_app(app)

    # Blueprint'ы.
    from blueprints.admin import admin_bp
    from blueprints.auth import auth_bp
    from blueprints.client import client_bp
    from blueprints.clients import clients_bp
    from blueprints.methodologist import methodologist_bp
    from blueprints.notifications import notifications_bp
    from blueprints.tasks import tasks_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(methodologist_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(notifications_bp)

    # Справочники доступны во всех шаблонах (для меток статусов/приоритетов/типов).
    @app.context_processor
    def inject_labels():
        return {
            "STATUS_LABELS": STATUS_LABELS,
            "PRIORITY_LABELS": PRIORITY_LABELS,
            "WORK_TYPE_LABELS": WORK_TYPE_LABELS,
            "ROLE_LABELS": ROLE_LABELS,
        }

    # Данные колокольчика для шапки (только для авторизованных).
    @app.context_processor
    def inject_notifications():
        from flask_login import current_user

        if not current_user.is_authenticated:
            return {}
        from services.notifications import recent, unread_count

        return {
            "nav_unread_count": unread_count(current_user.id),
            "nav_notifications": recent(current_user.id, limit=10),
        }

    # Инициализация БД и сид админа.
    with app.app_context():
        # Импорт моделей обязателен до create_all, чтобы таблицы зарегистрировались.
        import models  # noqa: F401
        from seed import seed_admin

        db.create_all()
        _ensure_columns()  # лёгкая «миграция» недостающих колонок (create_all не ALTER-ит)
        seed_admin(app)

    _init_scheduler(app)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
