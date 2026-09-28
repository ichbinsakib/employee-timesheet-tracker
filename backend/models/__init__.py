"""ORM models.

Written with portable SQLAlchemy types only, so the schema can move from
SQLite to PostgreSQL by changing DATABASE_URL.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def now() -> datetime:
    return datetime.now().replace(microsecond=0)


# --------------------------------------------------------------------------- people
class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    # Other spellings seen on timesheets, comma separated ("Kamrul Hasan, Md Kamrul")
    aliases: Mapped[str] = mapped_column(Text, default="")
    email: Mapped[str | None] = mapped_column(String(320), index=True)
    department: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))
    expected_daily_hours: Mapped[float] = mapped_column(Float, default=8.0)
    expected_weekly_hours: Mapped[float] = mapped_column(Float, default=40.0)
    # Comma separated weekday abbreviations
    working_days: Mapped[str] = mapped_column(String(64), default="Mon,Tue,Wed,Thu,Fri")
    # Local time (HH:MM) by which the day's timesheet is expected
    submission_deadline: Mapped[str] = mapped_column(String(5), default="18:00")
    # Missing-timesheet checks start from this date
    tracking_start: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_created: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    entries: Mapped[list["TimesheetEntry"]] = relationship(back_populates="employee")


# --------------------------------------------------------------------------- imports
class GmailMessage(Base):
    """Every Gmail message the sync has looked at, so nothing is processed twice."""
    __tablename__ = "gmail_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    thread_id: Mapped[str | None] = mapped_column(String(64))
    sender: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    email_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    attachments_found: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="processed")  # processed | no_attachment | skipped | error
    note: Mapped[str | None] = mapped_column(Text)


class Submission(Base):
    """One received timesheet file (from Gmail or a manual upload).

    This is the "Gmail Submissions" table from the spec, generalised so manual
    uploads share the same pipeline.
    """
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    source: Mapped[str] = mapped_column(String(16), default="gmail")  # gmail | upload
    gmail_message_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sender_email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(500))
    attachment_filename: Mapped[str] = mapped_column(String(500))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_path: Mapped[str | None] = mapped_column(Text)
    email_timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    import_timestamp: Mapped[datetime] = mapped_column(DateTime, default=now)
    work_date: Mapped[date | None] = mapped_column(Date, index=True)
    # imported | imported_with_warnings | failed | duplicate | superseded
    import_status: Mapped[str] = mapped_column(String(32), default="imported")
    # unique | duplicate_file | resubmission (replaced an earlier file for same employee+date)
    duplicate_status: Mapped[str] = mapped_column(String(32), default="unique")
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"))
    total_hours: Mapped[float | None] = mapped_column(Float)
    declared_total_hours: Mapped[float | None] = mapped_column(Float)
    entry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)

    employee: Mapped[Employee | None] = relationship(foreign_keys=[employee_id])
    entries: Mapped[list["TimesheetEntry"]] = relationship(back_populates="submission", cascade="all, delete-orphan")
    issues: Mapped[list["DataQualityIssue"]] = relationship(back_populates="submission", cascade="all, delete-orphan")


# --------------------------------------------------------------------------- timesheet data
class TimesheetEntry(Base):
    __tablename__ = "timesheet_entries"
    __table_args__ = (Index("ix_entries_emp_date", "employee_id", "work_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date, index=True)
    costing_code: Mapped[str | None] = mapped_column(String(100), index=True)
    title: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    file_type: Mapped[str | None] = mapped_column(String(100))
    completed: Mapped[bool | None] = mapped_column(Boolean)  # None = not recorded
    completed_raw: Mapped[str | None] = mapped_column(String(50))
    feature_count: Mapped[int | None] = mapped_column(Integer)
    burden_hours: Mapped[float | None] = mapped_column(Float)
    original_excel_row: Mapped[int | None] = mapped_column(Integer)
    sheet_name: Mapped[str | None] = mapped_column(String(200))
    primary_category_id: Mapped[int | None] = mapped_column(ForeignKey("work_categories.id"))

    submission: Mapped[Submission] = relationship(back_populates="entries")
    employee: Mapped[Employee] = relationship(back_populates="entries")
    primary_category: Mapped["WorkCategory | None"] = relationship()
    activities: Mapped[list["EntryActivity"]] = relationship(back_populates="entry", cascade="all, delete-orphan")


class EntryActivity(Base):
    """One bullet line inside an entry's notes, classified into a category.

    An entry's hours are split evenly across its activity lines, so category
    distribution is an *estimate* based on what was written.
    """
    __tablename__ = "entry_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("timesheet_entries.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    text: Mapped[str] = mapped_column(Text)
    normalized: Mapped[str] = mapped_column(String(500), index=True)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("work_categories.id"), index=True)
    matched_keyword: Mapped[str | None] = mapped_column(String(100))
    allocated_hours: Mapped[float] = mapped_column(Float, default=0.0)

    entry: Mapped[TimesheetEntry] = relationship(back_populates="activities")
    category: Mapped["WorkCategory | None"] = relationship()


class CostingCode(Base):
    """The company's costing codes (e.g. P0205 = "Manufacturing checksheet entry").

    Filled automatically from the "COSTING CODE" sheet inside received timesheets;
    descriptions can also be edited in Settings. Work is reported by these codes.
    """
    __tablename__ = "costing_codes"

    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="timesheet")  # timesheet | manual
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class WorkCategory(Base):
    __tablename__ = "work_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(16))


class ClassificationRule(Base):
    __tablename__ = "classification_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(200))
    category_id: Mapped[int] = mapped_column(ForeignKey("work_categories.id"))
    priority: Mapped[int] = mapped_column(Integer, default=50)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    category: Mapped[WorkCategory] = relationship()


class DataQualityIssue(Base):
    __tablename__ = "data_quality_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int | None] = mapped_column(ForeignKey("submissions.id"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"), index=True)
    work_date: Mapped[date | None] = mapped_column(Date, index=True)
    severity: Mapped[str] = mapped_column(String(16))  # info | warning | error
    code: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    excel_row: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    submission: Mapped[Submission | None] = relationship(back_populates="issues")


# --------------------------------------------------------------------------- auth
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20), default="admin")  # admin | manager | viewer
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))

    user: Mapped[User] = relationship()


class AccessLog(Base):
    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    username: Mapped[str | None] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(String(64))
    via: Mapped[str] = mapped_column(String(16))  # local | lan | tailscale
    event: Mapped[str] = mapped_column(String(32))  # login_ok | login_failed | logout | request
    method: Mapped[str | None] = mapped_column(String(8))
    path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[int | None] = mapped_column(Integer)


# --------------------------------------------------------------------------- system
class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(32), index=True)  # gmail_sync | backup | daily_report
    trigger: Mapped[str] = mapped_column(String(16), default="schedule")  # schedule | manual | startup
    started_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | ok | error
    message: Mapped[str | None] = mapped_column(Text)


class GeneratedReport(Base):
    __tablename__ = "generated_reports"
    __table_args__ = (UniqueConstraint("report_date", "fmt", name="uq_report_date_fmt"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, index=True)
    fmt: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
