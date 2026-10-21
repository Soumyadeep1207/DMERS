"""Narrow write boundary for AI audit records.

AI callers may persist advisory outputs and officer feedback only.  This is the
runtime guard used where a dedicated database role is not configured.
"""
from __future__ import annotations
import json
from sqlite3 import Connection

AI_WRITE_TABLES = frozenset({"ai_assessments", "ai_feedback"})

def save_assessment(db: Connection, incident_id: int | None, kind: str, output: dict, model_version: str, created_by: int) -> int:
    return db.execute("INSERT INTO ai_assessments(incident_id,kind,output_json,model_version,created_by) VALUES(?,?,?,?,?)", (incident_id, kind, json.dumps(output), model_version, created_by)).lastrowid

def save_feedback(db: Connection, assessment_id: int, officer_id: int, action: str, note: str = "") -> int:
    if action not in {"accepted", "overridden", "dismissed"}: raise ValueError("Invalid advisory feedback action")
    return db.execute("INSERT INTO ai_feedback(assessment_id,officer_id,action,note) VALUES(?,?,?,?)", (assessment_id, officer_id, action, note)).lastrowid
