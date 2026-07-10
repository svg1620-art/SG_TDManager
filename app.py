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

    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    _scheduler = BackgroundScheduler(timezone="UTC")
    # 1-е число каждого месяца в 00:05 — автосоздание месячных бюджетов.
    _scheduler.add_job(
        lambda: _monthly_budget_job(app),
        CronTrigger(day=1, hour=0, minute=5),
        id="monthly_budgets",
        replace_existing=True,
    )
    # Задачи Telegram-пульса и AI-отчётов (Стадии 7/8) добавим позже.
    _scheduler.start()
    logger.info("APScheduler запущен (задача monthly_budgets зарегистрирована).")


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

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(methodologist_bp)
    app.register_blueprint(client_bp)
    app.register_blueprint(clients_bp)

    # Справочники доступны во всех шаблонах (для меток статусов/приоритетов/типов).
    @app.context_processor
    def inject_labels():
        return {
            "STATUS_LABELS": STATUS_LABELS,
            "PRIORITY_LABELS": PRIORITY_LABELS,
            "WORK_TYPE_LABELS": WORK_TYPE_LABELS,
            "ROLE_LABELS": ROLE_LABELS,
        }

    # Инициализация БД и сид админа.
    with app.app_context():
        # Импорт моделей обязателен до create_all, чтобы таблицы зарегистрировались.
        import models  # noqa: F401
        from seed import seed_admin

        db.create_all()
        seed_admin(app)

    _init_scheduler(app)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
