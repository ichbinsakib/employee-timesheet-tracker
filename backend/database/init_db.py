"""Create tables and seed default categories, classification rules and settings."""
from __future__ import annotations

from sqlalchemy import select

from backend.config import settings
from backend.database.session import get_engine, session_scope
from backend.models import AppSetting, Base, ClassificationRule, WorkCategory

UNCATEGORIZED = "Uncategorized"

# name -> (description, color)
DEFAULT_CATEGORIES: dict[str, tuple[str, str]] = {
    "Design & Engineering": ("Drawings, models, assemblies, CAD and engineering changes", "#2a6fdb"),
    "Order Processing": ("Sales orders (SO), work orders, releases and order trackers", "#0f9d8a"),
    "Material & Shortage": ("Shortages, Kanban, inventory and material availability", "#d9822b"),
    "Purchasing & Vendors": ("Purchase orders, subcontracting, vendor quotes and invoices", "#8e5cd9"),
    "Planning & Scheduling": ("Master schedule, planning and days-behind tracking", "#c2410c"),
    "Communication": ("Email, Teams, meetings, calls and follow-ups", "#0284c7"),
    "Coordination": ("Coordinating work between people and departments", "#15803d"),
    "Administrative": ("Approvals, IT tickets, filing and general admin", "#b4235a"),
    "Data Entry & Reporting": ("Entering data, updating sheets, analysis and reports", "#6b7280"),
    "Quality & RMA": ("Quality checks, inspections, returns (RMA) and NCRs", "#a16207"),
    UNCATEGORIZED: ("Notes that matched no keyword rule", "#9ca3af"),
}

# (keyword, category, priority) — higher priority wins when several keywords match one line.
DEFAULT_RULES: list[tuple[str, str, int]] = [
    # Design & Engineering
    ("drawing", "Design & Engineering", 80), ("assembly", "Design & Engineering", 80),
    ("model", "Design & Engineering", 70), ("cad", "Design & Engineering", 80),
    ("solidworks", "Design & Engineering", 85), ("design", "Design & Engineering", 70),
    ("revision", "Design & Engineering", 60), ("bom", "Design & Engineering", 70),
    ("ecn", "Design & Engineering", 75), ("feature", "Design & Engineering", 55),
    # Order processing
    ("so release", "Order Processing", 75), ("so tracker", "Order Processing", 75),
    ("sales order", "Order Processing", 75), ("work order", "Order Processing", 70),
    ("so", "Order Processing", 45), ("order", "Order Processing", 40),
    # Material & shortage
    ("shortage", "Material & Shortage", 65), ("kanban", "Material & Shortage", 70),
    ("inventory", "Material & Shortage", 65), ("stock", "Material & Shortage", 55),
    ("material", "Material & Shortage", 55),
    # Purchasing
    ("po", "Purchasing & Vendors", 65), ("purchase order", "Purchasing & Vendors", 75),
    ("purchasing", "Purchasing & Vendors", 70), ("subcontract", "Purchasing & Vendors", 75),
    ("vendor", "Purchasing & Vendors", 70), ("quotation", "Purchasing & Vendors", 70),
    ("quote", "Purchasing & Vendors", 65), ("supplier", "Purchasing & Vendors", 70),
    ("invoice", "Purchasing & Vendors", 55),
    # Planning
    ("schedule", "Planning & Scheduling", 60), ("shudule", "Planning & Scheduling", 60),
    ("planning", "Planning & Scheduling", 60), ("days behind", "Planning & Scheduling", 55),
    ("forecast", "Planning & Scheduling", 55),
    # Communication
    ("email", "Communication", 50), ("e-mail", "Communication", 50), ("teams", "Communication", 50),
    ("meeting", "Communication", 55), ("call", "Communication", 45),
    ("communication", "Communication", 50), ("comunication", "Communication", 50),
    ("followup", "Communication", 45), ("follow up", "Communication", 45), ("follow-up", "Communication", 45),
    # Coordination
    ("coordination", "Coordination", 60), ("co-ordination", "Coordination", 60),
    ("coordinate", "Coordination", 60), ("coordinating", "Coordination", 60),
    # Administrative
    ("approve", "Administrative", 60), ("approval", "Administrative", 60),
    ("it ticket", "Administrative", 75), ("ticket", "Administrative", 55),
    ("admin", "Administrative", 55), ("filing", "Administrative", 55),
    ("timesheet", "Administrative", 55), ("training", "Administrative", 45),
    # Data entry & reporting
    ("data entry", "Data Entry & Reporting", 60), ("entering data", "Data Entry & Reporting", 60),
    ("analysis", "Data Entry & Reporting", 40), ("report", "Data Entry & Reporting", 40),
    ("sheet", "Data Entry & Reporting", 30), ("update", "Data Entry & Reporting", 25),
    ("matrix", "Data Entry & Reporting", 50), ("spreadsheet", "Data Entry & Reporting", 45),
    # Quality
    ("rma", "Quality & RMA", 80), ("quality", "Quality & RMA", 70),
    ("inspection", "Quality & RMA", 70), ("ncr", "Quality & RMA", 80), ("defect", "Quality & RMA", 70),
]

DEFAULT_APP_SETTINGS: dict[str, str] = {
    "gmail_query": settings.default_gmail_query,
    "gmail_lookback_days": str(settings.default_gmail_lookback_days),
    "gmail_allowed_senders": "",  # comma separated emails or @domains; empty = any sender
    "sync_interval_minutes": str(settings.default_sync_interval_minutes),
    "backup_interval_hours": str(settings.default_backup_interval_hours),
    "backup_retention": str(settings.default_backup_retention),
    "daily_report_time": settings.default_report_time,
    "holidays": "",  # comma separated YYYY-MM-DD
    "unusual_hours_threshold": "12",
}


def init_db(seed: bool = True) -> None:
    settings.ensure_dirs()
    engine = get_engine()
    Base.metadata.create_all(engine)
    if seed:
        seed_defaults()


def seed_defaults() -> None:
    with session_scope() as db:
        existing = {c.name: c for c in db.scalars(select(WorkCategory))}
        for name, (desc, color) in DEFAULT_CATEGORIES.items():
            if name not in existing:
                cat = WorkCategory(name=name, description=desc, color=color)
                db.add(cat)
                existing[name] = cat
        db.flush()

        # Only seed rules on a brand-new database, so user edits are never overwritten.
        if db.scalar(select(ClassificationRule.id).limit(1)) is None:
            for keyword, cat_name, priority in DEFAULT_RULES:
                db.add(ClassificationRule(keyword=keyword, category_id=existing[cat_name].id, priority=priority))

        have = set(db.scalars(select(AppSetting.key)))
        for key, value in DEFAULT_APP_SETTINGS.items():
            if key not in have:
                db.add(AppSetting(key=key, value=value))
