"""Справочники и enum-подобные строковые константы (переиспользуются во всех стадиях)."""

# --- Роли пользователей ---
ROLE_ADMIN = "admin"
ROLE_METHODOLOGIST = "methodologist"
ROLE_CLIENT = "client"

ROLES = (ROLE_ADMIN, ROLE_METHODOLOGIST, ROLE_CLIENT)

ROLE_LABELS = {
    ROLE_ADMIN: "Администратор",
    ROLE_METHODOLOGIST: "Методолог",
    ROLE_CLIENT: "Клиент",
}

# --- Статусы задач (жизненный цикл) ---
STATUS_NEW = "new"
STATUS_ESTIMATE_PENDING = "estimate_pending"
STATUS_APPROVED = "approved"
STATUS_IN_PROGRESS = "in_progress"
STATUS_CLARIFICATION = "clarification"
STATUS_DONE = "done"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

TASK_STATUSES = (
    STATUS_NEW,
    STATUS_ESTIMATE_PENDING,
    STATUS_APPROVED,
    STATUS_IN_PROGRESS,
    STATUS_CLARIFICATION,
    STATUS_DONE,
    STATUS_ACCEPTED,
    STATUS_REJECTED,
)

STATUS_LABELS = {
    STATUS_NEW: "Новая",
    STATUS_ESTIMATE_PENDING: "Ожидает подтверждения",
    STATUS_APPROVED: "Готова к работе",
    STATUS_IN_PROGRESS: "В работе",
    STATUS_CLARIFICATION: "На уточнении",
    STATUS_DONE: "Выполнена",
    STATUS_ACCEPTED: "Принята",
    STATUS_REJECTED: "Отклонена",
}

# --- Приоритеты ---
PRIORITY_LOW = "low"
PRIORITY_MEDIUM = "medium"
PRIORITY_HIGH = "high"
PRIORITY_URGENT = "urgent"

PRIORITIES = (PRIORITY_LOW, PRIORITY_MEDIUM, PRIORITY_HIGH, PRIORITY_URGENT)

PRIORITY_LABELS = {
    PRIORITY_LOW: "Низкий",
    PRIORITY_MEDIUM: "Средний",
    PRIORITY_HIGH: "Высокий",
    PRIORITY_URGENT: "Срочный",
}

# --- Типы работ ---
WORK_CONTENT = "content"
WORK_SETUP = "setup"
WORK_COMMUNICATION = "communication"
WORK_PLATFORM = "platform"
WORK_ATTESTATION = "attestation"
WORK_REPORTS = "reports"
WORK_OTHER = "other"

WORK_TYPES = (
    WORK_CONTENT,
    WORK_SETUP,
    WORK_COMMUNICATION,
    WORK_PLATFORM,
    WORK_ATTESTATION,
    WORK_REPORTS,
    WORK_OTHER,
)

WORK_TYPE_LABELS = {
    WORK_CONTENT: "Контент",
    WORK_SETUP: "Настройка",
    WORK_COMMUNICATION: "Коммуникация",
    WORK_PLATFORM: "Работа с платформой",
    WORK_ATTESTATION: "Аттестации",
    WORK_REPORTS: "Отчёты",
    WORK_OTHER: "Прочее",
}

# --- Источник месячного отчёта ---
REPORT_SOURCE_AUTO = "auto"
REPORT_SOURCE_MANUAL = "manual"

# --- Цвета статусов для графиков (согласованы с бейджами карточек) ---
STATUS_COLORS = {
    STATUS_NEW: "#6b7280",
    STATUS_ESTIMATE_PENDING: "#9aa0ac",
    STATUS_APPROVED: "#4a7fe0",
    STATUS_IN_PROGRESS: "#1467f5",
    STATUS_CLARIFICATION: "#f5b014",
    STATUS_DONE: "#00bfdc",
    STATUS_ACCEPTED: "#35d0a0",
    STATUS_REJECTED: "#7a4a52",
}

# Палитра для сегментов (типы работ, клиенты) — фирменные и производные оттенки.
CHART_PALETTE = [
    "#1467f5",
    "#00bfdc",
    "#4a7fe0",
    "#2fd0c0",
    "#7a6cf0",
    "#35d0a0",
    "#9aa0ac",
    "#f5b014",
]

# --- Типы уведомлений (колокольчик) ---
NOTIF_NEW_TASK = "new_task"
NOTIF_ESTIMATE_SET = "estimate_set"
NOTIF_ESTIMATE_APPROVED = "estimate_approved"
NOTIF_TASK_DONE = "task_done"
NOTIF_TASK_RETURNED = "task_returned"
NOTIF_TASK_ACCEPTED = "task_accepted"
NOTIF_CLARIFICATION = "clarification"
NOTIF_TASK_REJECTED = "task_rejected"
NOTIF_NEW_COMMENT = "new_comment"
NOTIF_CLIENT_ASSIGNED = "client_assigned"
NOTIF_CLIENT_TRANSFERRED = "client_transferred"
