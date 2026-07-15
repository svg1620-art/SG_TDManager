"""Полная схема БД SG_T&D_manager.

Реализованы ВСЕ таблицы из CLAUDE.md/ТЗ, даже те, что не используются в Стадии 1
(tasks, time_entries, comments, notifications, monthly_budgets, budget_adjustments,
monthly_reports) — чтобы зафиксировать схему на старте.
"""
from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from constants import (
    PRIORITY_MEDIUM,
    REPORT_SOURCE_AUTO,
    ROLE_ADMIN,
    ROLE_CLIENT,
    ROLE_METHODOLOGIST,
    STATUS_NEW,
    WORK_OTHER,
)
from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)  # admin | methodologist | client
    full_name = db.Column(db.String(200), nullable=False)
    login = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(200), nullable=True)
    # client_id заполняется только для роли client (принадлежность к организации).
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=True, index=True
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Организация, к которой принадлежит сотрудник-клиент.
    organization = db.relationship(
        "ClientOrg",
        foreign_keys=[client_id],
        back_populates="employees",
    )
    # Организации, которые ведёт этот методолог.
    managed_clients = db.relationship(
        "ClientOrg",
        foreign_keys="ClientOrg.methodologist_id",
        back_populates="methodologist",
    )

    # --- Пароли ---
    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    # --- Роль-хелперы ---
    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_methodologist(self) -> bool:
        return self.role == ROLE_METHODOLOGIST

    @property
    def is_client(self) -> bool:
        return self.role == ROLE_CLIENT

    def __repr__(self) -> str:
        return f"<User {self.login} ({self.role})>"


class ClientOrg(db.Model):
    """Организация-клиент. Лимит часов — общий на организацию."""

    __tablename__ = "client_orgs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    methodologist_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    telegram_chat_id = db.Column(db.String(64), nullable=True)
    default_monthly_hours = db.Column(db.Numeric(8, 2), default=0, nullable=False)
    contract_months = db.Column(db.Integer, nullable=True)  # 3 | 6 | 12
    contract_start = db.Column(db.Date, nullable=True)
    contract_end = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    methodologist = db.relationship(
        "User",
        foreign_keys=[methodologist_id],
        back_populates="managed_clients",
    )
    employees = db.relationship(
        "User",
        foreign_keys="User.client_id",
        back_populates="organization",
    )
    tasks = db.relationship(
        "Task", back_populates="client", cascade="all, delete-orphan"
    )
    budgets = db.relationship(
        "MonthlyBudget", back_populates="client", cascade="all, delete-orphan"
    )
    adjustments = db.relationship(
        "BudgetAdjustment", back_populates="client", cascade="all, delete-orphan"
    )
    reports = db.relationship(
        "MonthlyReport", back_populates="client", cascade="all, delete-orphan"
    )
    reassignments = db.relationship(
        "ClientReassignment", back_populates="client", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ClientOrg {self.name}>"


class MonthlyBudget(db.Model):
    """Базовый месячный лимит клиента. Эффективный лимит = base + Σ adjustments за месяц."""

    __tablename__ = "monthly_budgets"
    __table_args__ = (
        db.UniqueConstraint("client_id", "year", "month", name="uq_budget_client_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=False, index=True
    )
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    base_limit_hours = db.Column(db.Numeric(8, 2), default=0, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    client = db.relationship("ClientOrg", back_populates="budgets")
    creator = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<MonthlyBudget client={self.client_id} {self.year}-{self.month:02d}>"


class BudgetAdjustment(db.Model):
    """Аудит ручного добавления часов (расширение тарифа)."""

    __tablename__ = "budget_adjustments"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=False, index=True
    )
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    delta_hours = db.Column(db.Numeric(8, 2), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    client = db.relationship("ClientOrg", back_populates="adjustments")
    creator = db.relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<BudgetAdjustment client={self.client_id} {self.delta_hours}h>"


class Task(db.Model):
    __tablename__ = "tasks"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=False, index=True
    )
    created_by = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)
    priority = db.Column(db.String(20), default=PRIORITY_MEDIUM, nullable=False)
    work_type = db.Column(db.String(30), default=WORK_OTHER, nullable=False)
    status = db.Column(db.String(30), default=STATUS_NEW, nullable=False, index=True)
    estimated_hours = db.Column(db.Numeric(8, 2), nullable=True)
    # actual_hours — кэш Σ time_entries (пересчёт добавим в Стадии 4).
    actual_hours = db.Column(db.Numeric(8, 2), default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    closed_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    return_reason = db.Column(db.Text, nullable=True)

    client = db.relationship("ClientOrg", back_populates="tasks")
    author = db.relationship("User", foreign_keys=[created_by])
    time_entries = db.relationship(
        "TimeEntry", back_populates="task", cascade="all, delete-orphan"
    )
    comments = db.relationship(
        "Comment", back_populates="task", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Task #{self.id} {self.status}>"


class TimeEntry(db.Model):
    """Запись реально отработанного времени по задаче."""

    __tablename__ = "time_entries"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True
    )
    methodologist_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    hours = db.Column(db.Numeric(8, 2), nullable=False)
    work_date = db.Column(db.Date, default=date.today, nullable=False, index=True)
    note = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    task = db.relationship("Task", back_populates="time_entries")
    methodologist = db.relationship("User", foreign_keys=[methodologist_id])

    def __repr__(self) -> str:
        return f"<TimeEntry task={self.task_id} {self.hours}h>"


class Comment(db.Model):
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(
        db.Integer, db.ForeignKey("tasks.id"), nullable=False, index=True
    )
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    task = db.relationship("Task", back_populates="comments")
    author = db.relationship("User", foreign_keys=[author_id])

    def __repr__(self) -> str:
        return f"<Comment task={self.task_id}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    type = db.Column(db.String(50), nullable=False)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), nullable=True)
    body = db.Column(db.Text, nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id])
    task = db.relationship("Task", foreign_keys=[task_id])

    def __repr__(self) -> str:
        return f"<Notification user={self.user_id} {self.type}>"


class MonthlyReport(db.Model):
    __tablename__ = "monthly_reports"
    __table_args__ = (
        db.UniqueConstraint("client_id", "year", "month", name="uq_report_client_period"),
    )

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=False, index=True
    )
    year = db.Column(db.Integer, nullable=False)
    month = db.Column(db.Integer, nullable=False)
    body_text = db.Column(db.Text, nullable=True)
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    source = db.Column(db.String(20), default=REPORT_SOURCE_AUTO, nullable=False)

    client = db.relationship("ClientOrg", back_populates="reports")

    def __repr__(self) -> str:
        return f"<MonthlyReport client={self.client_id} {self.year}-{self.month:02d}>"


class AppSetting(db.Model):
    """Простое key-value хранилище настроек приложения (напр. общий чат отчёта)."""

    __tablename__ = "app_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=True)

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}={self.value!r}>"


class ClientReassignment(db.Model):
    """Аудит передачи клиента между методологами (Стадия 6)."""

    __tablename__ = "client_reassignments"

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(
        db.Integer, db.ForeignKey("client_orgs.id"), nullable=False, index=True
    )
    from_methodologist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    to_methodologist_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    client = db.relationship("ClientOrg", back_populates="reassignments")
    from_methodologist = db.relationship("User", foreign_keys=[from_methodologist_id])
    to_methodologist = db.relationship("User", foreign_keys=[to_methodologist_id])
    changer = db.relationship("User", foreign_keys=[changed_by])

    def __repr__(self) -> str:
        return f"<ClientReassignment client={self.client_id} -> {self.to_methodologist_id}>"
