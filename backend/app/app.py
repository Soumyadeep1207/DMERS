from __future__ import annotations
import os, random, math
from functools import wraps
import jwt
from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from .database import connection, init_db, save_simulation, simulations, database_health
from .search import search
from ai import service as ai_service
from ai.store import save_assessment, save_feedback

def create_app() -> Flask:
    app = Flask(__name__); CORS(app)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-development-key")
    init_db()
    def token_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            try: request.user = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            except jwt.PyJWTError: return jsonify(error="Authentication required"), 401
            return fn(*args, **kwargs)
        return wrapped
    def issue(user: dict) -> str:
        return jwt.encode({"id": user["id"], "email": user["email"], "role": user["role"]}, app.config["SECRET_KEY"], algorithm="HS256")
    def audit(actor_id: int | None, action: str, subject: str, details: str = "") -> None:
        with connection() as db: db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (actor_id, action, subject, details))
    def role_required(*roles: str):
        def decorator(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                if request.user.get("role") not in roles: return jsonify(error="This action requires an authorised government or administrator account"), 403
                return fn(*args, **kwargs)
            return wrapped
        return decorator
    @app.get("/api/health")
    def health():
        """Container health probe; no credentials or internal details exposed."""
        return jsonify(status="ok", service="dmers-backend")
    @app.post("/api/auth/register")
    def register():
        data = request.get_json() or {}; name, email, password = data.get("name", ""), data.get("email", "").lower(), data.get("password", "")
        role = data.get("role", "citizen") if data.get("role") in {"citizen", "volunteer", "responder"} else "citizen"
        if not name or "@" not in email or len(password) < 6: return jsonify(error="Provide a name, valid email, and password of 6+ characters"), 400
        try:
            with connection() as db:
                cur = db.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", (name, email, generate_password_hash(password), role)); user = dict(db.execute("SELECT id,name,email,role FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
        except Exception: return jsonify(error="Email is already registered"), 409
        return jsonify(token=issue(user), user=user), 201
    @app.post("/api/auth/login")
    def login():
        data = request.get_json() or {}
        with connection() as db: row = db.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").lower(),)).fetchone()
        if not row or not check_password_hash(row["password"], data.get("password", "")): return jsonify(error="Invalid credentials"), 401
        user = {k: row[k] for k in ("id", "name", "email", "role")}; return jsonify(token=issue(user), user=user)
    @app.post("/api/missions/claim")
    @token_required
    @role_required("admin", "official")
    def claim_mission():
        data = request.get_json() or {}; report_id, team = data.get("reportId", "").strip(), data.get("team", "").strip()
        if not report_id or not team: return jsonify(error="Report ID and rescue team are required"), 400
        try:
            with connection() as db:
                cur = db.execute("INSERT INTO missions(report_id,team_name,assigned_by) VALUES(?,?,?)", (report_id, team, request.user["id"])); mission_id = cur.lastrowid
                db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "MISSION_ASSIGNED", report_id, f"Mission {mission_id} assigned to {team}"))
            return jsonify(id=mission_id, reportId=report_id, team=team, status="assigned"), 201
        except Exception:
            return jsonify(error="This incident already has an active rescue mission. Release or close it before reassignment."), 409
    @app.post("/api/missions/<int:mission_id>/status")
    @token_required
    @role_required("admin", "official")
    def update_mission(mission_id: int):
        data = request.get_json() or {}; status = data.get("status", "")
        if status not in {"assigned", "acknowledged", "en_route", "on_scene", "in_progress", "at_hospital", "completed", "escalated", "aborted"}: return jsonify(error="Invalid mission state"), 400
        with connection() as db:
            mission = db.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
            if not mission: return jsonify(error="Mission not found"), 404
            db.execute("UPDATE missions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, mission_id)); db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "MISSION_STATUS", mission["report_id"], f"Mission {mission_id} changed to {status}"))
        return jsonify(id=mission_id, status=status)
    @app.get("/api/audit")
    @token_required
    @role_required("admin", "official")
    def audit_log():
        with connection() as db: rows = [dict(row) for row in db.execute("SELECT audit_entries.*, users.name AS actor_name FROM audit_entries LEFT JOIN users ON users.id=audit_entries.actor_id ORDER BY audit_entries.id DESC LIMIT 50")]
        return jsonify(entries=rows)
    @app.post("/api/search")
    def run_search():
        data = request.get_json() or {}
        try: return jsonify(search(data["grid"], tuple(data["start"]), tuple(data["goal"]), data.get("algorithm", "astar")).as_dict())
        except (KeyError, TypeError, ValueError) as e: return jsonify(error=str(e)), 400
    @app.post("/api/compare")
    def compare():
        data = request.get_json() or {}; algorithms = ["bfs", "dfs", "ucs", "greedy", "astar"]
        try: return jsonify(results={a: search(data["grid"], tuple(data["start"]), tuple(data["goal"]), a).as_dict() for a in algorithms})
        except (KeyError, TypeError, ValueError) as e: return jsonify(error=str(e)), 400
    @app.post("/api/planning")
    def planning():
        data = request.get_json() or {}; grid, current = data["grid"], tuple(data["team"]); victims = [tuple(v) for v in data.get("victims", [])]; order=[]; total=0
        while victims:
            scored = [(search(grid, current, v, "astar"), v) for v in victims]; result, chosen = min(scored, key=lambda x: x[0].cost if x[0].found else float("inf"))
            if not result.found: break
            order.append({"victim": chosen, "path": result.path, "cost": result.cost}); total += result.cost; current=chosen; victims.remove(chosen)
        return jsonify(order=order, totalCost=total, unreachable=victims)
    @app.post("/api/simulation")
    def simulation():
        data=request.get_json() or {}; size=max(8, min(40, int(data.get("size", 20)))); obstacles=int(data.get("obstacles", 35)); victims=int(data.get("victims", 3)); condition=data.get("roadCondition", "normal")
        grid=[[1 for _ in range(size)] for _ in range(size)]; cells=[(r,c) for r in range(size) for c in range(size) if (r,c) not in [(0,0),(size-1,size-1)]]; random.shuffle(cells)
        blocked=cells[:min(obstacles,len(cells)-victims)];
        for r,c in blocked: grid[r][c]=-1
        free=[p for p in cells if p not in blocked]; selected=free[:victims]
        if condition == "poor":
            for r,c in free[victims:]: grid[r][c]=random.choice([1,1,2,3])
        return jsonify(grid=grid, team=[0,0], hospital=[size-1,size-1], victims=[list(v) for v in selected], disasterType=data.get("disasterType", "flood"), obstacles=[list(x) for x in blocked])
    @app.post("/api/map/route")
    def map_route():
        """Return an offline straight-line route estimate between supplied stops."""
        data = request.get_json() or {}
        try:
            stops = data.get("stops") or [data["start"], data["end"]]
            if len(stops) < 2 or not all(isinstance(point, list) and len(point) == 2 for point in stops):
                raise ValueError("Provide at least two stops as [latitude, longitude]")
            points = [[float(point[0]), float(point[1])] for point in stops]
            def meters(start, end):
                latitude = math.radians((start[0] + end[0]) / 2)
                return math.hypot((start[0] - end[0]) * 111_320, (start[1] - end[1]) * 111_320 * math.cos(latitude))
            total = sum(meters(points[index], points[index + 1]) for index in range(len(points) - 1))
            # 30 km/h is a conservative planning estimate only, not live traffic data.
            return jsonify(points=points, stops=points, distanceMeters=round(total, 1), durationSeconds=round(total / 8.33, 1), offline=True)
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400
    @app.get("/api/map/simulations")
    @token_required
    def saved(): return jsonify(simulations=simulations())
    @app.post("/api/map/simulations")
    @token_required
    def save():
        data=request.get_json() or {}; return jsonify(id=save_simulation(data.get("name", "Untitled scenario"), data.get("scenario", {}), request.user["id"])), 201
    @app.get("/api/admin/stats")
    @token_required
    def stats():
        if request.user["role"] != "admin": return jsonify(error="Admin role required"), 403
        with connection() as db: users=db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        return jsonify(users=users, simulations=len(simulations()), status="operational")

    @app.get("/api/data/health")
    @token_required
    def data_health():
        return jsonify(database_health())

    @app.get("/api/data/overview")
    @token_required
    def data_overview():
        with connection() as db:
            counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("users", "incidents", "missions", "rescue_teams", "hospitals", "audit_entries")}
            severity = [dict(row) for row in db.execute("SELECT severity, COUNT(*) AS count FROM incidents GROUP BY severity ORDER BY count DESC")]
            recent = [dict(row) for row in db.execute("SELECT i.reference,i.disaster_type,i.severity,i.status,l.label AS location FROM incidents i JOIN locations l ON l.id=i.location_id ORDER BY i.created_at DESC LIMIT 10")]
        return jsonify(counts=counts, severity=severity, incidents=recent)

    @app.get("/api/incidents")
    @token_required
    def list_incidents():
        with connection() as db:
            rows = [dict(row) for row in db.execute("SELECT i.*,l.label AS location,l.latitude,l.longitude,u.name AS reporter FROM incidents i JOIN locations l ON l.id=i.location_id LEFT JOIN users u ON u.id=i.reported_by ORDER BY i.created_at DESC")]
        return jsonify(incidents=rows)

    @app.post("/api/incidents")
    @token_required
    @role_required("admin", "official", "responder")
    def create_incident():
        data = request.get_json() or {}
        disaster_type, severity, description = data.get("disasterType", "").strip(), data.get("severity", "").lower(), data.get("description", "").strip()
        location = data.get("location", {})
        if not disaster_type or severity not in {"low","moderate","high","critical"} or not description or not location.get("label", "").strip(): return jsonify(error="Disaster type, severity, description, and location are required"), 400
        reference = data.get("reference", f"INC-{random.randint(100000,999999)}")
        try:
            with connection() as db:
                loc = db.execute("INSERT INTO locations(label,latitude,longitude,address) VALUES(?,?,?,?)", (location["label"].strip(),location.get("latitude"),location.get("longitude"),location.get("address"))).lastrowid
                incident = db.execute("INSERT INTO incidents(reference,disaster_type,severity,description,location_id,reported_by) VALUES(?,?,?,?,?,?)", (reference,disaster_type,severity,description,loc,request.user["id"])).lastrowid
                db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"],"INCIDENT_CREATED",reference,"Incident and location created transactionally"))
            return jsonify(id=incident, reference=reference), 201
        except Exception as error: return jsonify(error=f"Incident could not be saved: {error}"), 409

    @app.patch("/api/incidents/<int:incident_id>")
    @token_required
    @role_required("admin", "official", "responder")
    def update_incident(incident_id):
        data = request.get_json() or {}; status, severity = data.get("status"), data.get("severity")
        if status not in {"reported","verified","dispatched","resolved","closed"} or severity not in {"low","moderate","high","critical"}: return jsonify(error="Valid status and severity are required"), 400
        with connection() as db:
            item = db.execute("SELECT reference FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if not item: return jsonify(error="Incident not found"), 404
            db.execute("UPDATE incidents SET status=?,severity=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status,severity,incident_id))
            db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"],"INCIDENT_UPDATED",item["reference"],f"Status={status}; severity={severity}"))
        return jsonify(id=incident_id,status=status,severity=severity)

    @app.get("/api/rescue-teams")
    @token_required
    def rescue_teams():
        with connection() as db: rows=[dict(row) for row in db.execute("SELECT * FROM rescue_teams ORDER BY name")]
        return jsonify(teams=rows)

    @app.get("/api/hospitals")
    @token_required
    def hospitals():
        with connection() as db: rows=[dict(row) for row in db.execute("SELECT h.*,l.label AS location FROM hospitals h LEFT JOIN locations l ON l.id=h.location_id ORDER BY available_beds DESC")]
        return jsonify(hospitals=rows)

    # AI endpoints are strictly advisory. They may read operational data but
    # persist only AI audit rows through ai.store's narrow allow-list.
    def persist_ai(kind, result, data):
        with connection() as db:
            assessment_id = save_assessment(db, data.get("incident_id"), kind, result, result.get("model_version", ai_service.VERSION), request.user["id"])
        return assessment_id

    @app.post("/api/ai/classify")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_classify():
        data=request.get_json() or {}
        if not data.get("description", "").strip(): return jsonify(error="Report description is required"), 400
        result=ai_service.classify(data["description"], data.get("reported_type", "")); result["assessment_id"]=persist_ai("classification", result, data)
        return jsonify(result)

    @app.post("/api/ai/severity")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_severity():
        data=request.get_json() or {}
        result=ai_service.severity(data); result["assessment_id"]=persist_ai("severity", result, data)
        return jsonify(result)

    @app.post("/api/ai/assess")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_assess():
        data=request.get_json() or {}
        with connection() as db:
            teams=[dict(row) for row in db.execute("SELECT * FROM rescue_teams")]
            hospitals_data=[dict(row) for row in db.execute("SELECT * FROM hospitals")]
        result=ai_service.assess(data, teams, hospitals_data); result["assessment_id"]=persist_ai("assessment", result, data)
        return jsonify(result)

    @app.get("/api/ai/incidents/<int:incident_id>/duplicates")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_duplicates(incident_id):
        with connection() as db:
            records=[dict(row) for row in db.execute("SELECT i.*,l.label AS location FROM incidents i JOIN locations l ON l.id=i.location_id")]
        target=next((item for item in records if item["id"] == incident_id), None)
        if not target: return jsonify(error="Incident not found"), 404
        result={"duplicates": ai_service.duplicates(target, records), "model_version": ai_service.VERSION, "limitations": ai_service.LIMITATIONS, "source": "rules_fallback"}
        result["assessment_id"]=persist_ai("duplicates", result, {"incident_id": incident_id})
        return jsonify(result)

    @app.post("/api/ai/credibility")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_credibility():
        data=request.get_json() or {}; result=ai_service.credibility(data); result["assessment_id"]=persist_ai("credibility", result, data)
        return jsonify(result)

    @app.get("/api/ai/forecast")
    @token_required
    @role_required("admin", "official", "responder")
    def ai_forecast():
        days=max(1, min(30, request.args.get("days", 7, type=int)))
        with connection() as db: incidents=[dict(row) for row in db.execute("SELECT * FROM incidents")]
        result=ai_service.forecast(incidents, request.args.get("region", ""), request.args.get("type", ""), days); result["assessment_id"]=persist_ai("forecast", result, {})
        return jsonify(result)

    @app.post("/api/ai/feedback")
    @token_required
    @role_required("admin", "official")
    def ai_feedback():
        data=request.get_json() or {}
        if not isinstance(data.get("assessment_id"), int): return jsonify(error="assessment_id is required"), 400
        try:
            with connection() as db: feedback_id=save_feedback(db, data["assessment_id"], request.user["id"], data.get("action", ""), data.get("note", ""))
            return jsonify(id=feedback_id, message="Feedback recorded for later evaluation; no online retraining occurs."), 201
        except ValueError as error: return jsonify(error=str(error)), 400
    return app

if __name__ == "__main__": create_app().run(debug=True, port=5000)
