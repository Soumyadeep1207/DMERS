"""Translate PostgreSQL errors into HTTP-friendly ApiError objects.

Nothing raw reaches the user: constraint violations become readable messages that name the
constraint, errors raised by the procedures and triggers (SQLSTATE P0001, RAISE EXCEPTION) pass
their own message through, and anything unexpected becomes a generic 500.
"""
from __future__ import annotations

import logging

import psycopg
from psycopg import errors as pg

log = logging.getLogger("dmers.db")

FRIENDLY = {
    "uq_users_email": "That e-mail address is already registered.",
    "users_email_key": "That e-mail address is already registered.",
    "uq_zones_name": "A zone with that name already exists.",
    "uq_units_name": "A response unit with that name already exists.",
    "uq_resources_name": "A relief item with that name already exists.",
    "uq_units_lead": "That account already leads another unit (an account leads at most one unit).",
    "ck_zones_risk_level": "Risk level must be LOW, MEDIUM or HIGH.",
    "ck_units_type": "Unit type must be FIRE, MEDICAL, POLICE, RESCUE or RELIEF.",
    "ck_units_personnel": "A unit needs at least one person.",
    "ck_resources_category": "Category must be FOOD, WATER, MEDICAL, SHELTER or EQUIPMENT.",
    "fk_units_zone": "The chosen base zone does not exist.",
    "fk_units_lead": "The chosen lead account does not exist.",
    "uq_dispatches_one_active_per_unit": "That unit already has an active dispatch (rule BR-05).",
    "pk_dispatches": "That unit has already been dispatched to this incident.",
    "ck_users_account_type": "Account type must be CITIZEN, COORDINATOR, UNIT_LEAD or ADMINISTRATOR.",
    "ck_incidents_severity": "Severity must be LOW, MODERATE, HIGH or CRITICAL.",
    "ck_incidents_status": "Status must be REPORTED, VERIFIED, RESPONDING, RESOLVED, CLOSED or REJECTED.",
    "ck_incidents_zone_when_verified": "A verified incident must be assigned to a zone (FR-05).",
    "ck_resources_quantity": "Stock cannot fall below zero.",
    "ck_resources_reorder": "The reorder level cannot be negative.",
    "ck_allocations_quantity": "The allocated quantity must be greater than zero.",
    "ck_dispatches_arrival": "A unit cannot arrive before it was dispatched (BR-06).",
    "ck_dispatches_clearance": "A unit cannot clear before it arrived or was dispatched.",
    "ck_dispatches_arrived_on_scene": "A dispatch cannot be ON_SCENE or COMPLETED without an arrival time.",
    "ck_dispatches_cleared_when_closed": "A completed or cancelled dispatch needs a clearance time, and an open one must not have it.",
    "ck_units_phone": "A unit's phone number must be ten digits starting with 6-9.",
    "ck_updates_first_entry": "Only the first timeline entry may lack a previous status.",
    "fk_incidents_zone": "The chosen zone does not exist.",
    "fk_incidents_reporter": "The reporting user does not exist.",
    "fk_dispatches_unit": "The chosen unit does not exist.",
    "fk_dispatches_incident": "The incident does not exist.",
    "fk_allocations_resource": "The chosen relief item does not exist.",
    "fk_allocations_incident": "The incident does not exist.",
    "ex_reservations_no_overlap": "That unit is already reserved for part of this time (an overlapping booking exists).",
    "ck_reservations_period": "A reservation needs a closed, non-empty time range.",
    "ck_reservations_purpose": "Purpose must be STANDBY, TRAINING, MAINTENANCE or EXERCISE.",
    "fk_reservations_unit": "The chosen unit does not exist.",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, constraint: str | None = None,
                 sqlstate: str | None = None, trace: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.constraint, self.sqlstate, self.trace = constraint, sqlstate, trace

    def body(self) -> dict:
        body = {"error": self.message, "code": self.code}
        if self.constraint:
            body["constraint"] = self.constraint
        if self.sqlstate:
            body["sqlstate"] = self.sqlstate
        if self.trace is not None:
            body["db_trace"] = self.trace
        return body


def map_error(exc: Exception) -> ApiError:
    """Return the ApiError for a database exception (or the exception itself if it already is one)."""
    if isinstance(exc, ApiError):
        return exc
    trace = getattr(exc, "db_trace", None)
    diag = getattr(exc, "diag", None)
    constraint = getattr(diag, "constraint_name", None) if diag else None
    primary = (getattr(diag, "message_primary", None) or "") if diag else ""
    sqlstate = getattr(exc, "sqlstate", None)
    text = FRIENDLY.get(constraint or "", "")
    common = {"constraint": constraint, "sqlstate": sqlstate, "trace": trace}
    if isinstance(exc, pg.UniqueViolation):
        return ApiError(409, "unique_violation", text or "That record already exists.", **common)
    if isinstance(exc, pg.ExclusionViolation):
        return ApiError(409, "exclusion_violation", text or "That booking overlaps an existing one.", **common)
    if isinstance(exc, pg.CheckViolation):
        return ApiError(422, "check_violation", text or f"A data rule was violated ({constraint}).", **common)
    if isinstance(exc, pg.ForeignKeyViolation):
        if "update or delete" in primary:   # ON DELETE RESTRICT / NO ACTION blocked the delete
            return ApiError(409, "restricted", "This record has history (dispatches, allocations or timeline) and cannot be deleted.", **common)
        return ApiError(422, "foreign_key_violation", text or f"A referenced record does not exist ({constraint}).", **common)
    if isinstance(exc, pg.NotNullViolation):
        column = getattr(diag, "column_name", None) or "a required field"
        return ApiError(422, "not_null_violation", f"{column} is required.", **common)
    if isinstance(exc, pg.RaiseException):  # RAISE EXCEPTION in a procedure or trigger: its message is meant for people
        return ApiError(422, "rule_violation", primary or "The database rejected this operation.", sqlstate=sqlstate, trace=trace)
    if isinstance(exc, (pg.StringDataRightTruncation, pg.InvalidTextRepresentation, pg.NumericValueOutOfRange, pg.InvalidDatetimeFormat)):
        return ApiError(422, "invalid_value", "One of the values is too long or in the wrong format.", sqlstate=sqlstate, trace=trace)
    if isinstance(exc, (pg.LockNotAvailable, pg.DeadlockDetected, psycopg.OperationalError)):
        return ApiError(503, "database_busy", "The database is busy or unavailable. Please retry.", sqlstate=sqlstate, trace=trace)
    log.exception("Unexpected database error")
    return ApiError(500, "database_error", "The operation failed. Nothing was changed.", sqlstate=sqlstate, trace=trace)
