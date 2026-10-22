from __future__ import annotations
import os, random, math
from datetime import datetime, timedelta, timezone
from functools import wraps
import jwt
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from werkzeug.security import check_password_hash, generate_password_hash
from .database import connection, init_db, save_simulation, simulations, database_health, review2_connection, review2_database_health, is_integrity_error, using_postgres
from .search import search
from .decision_support import build_advisory
from .route_advisor import plan_response_route
from . import road_network, schema_export

TOKEN_LIFETIME = timedelta(hours=int(os.getenv("DMERS_TOKEN_HOURS", "8")))

def create_app() -> Flask:
    app = Flask(__name__); CORS(app)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-development-key")
    init_db()
    @app.get("/health")
    @app.get("/api/health")
    def health():
        database = database_health()
        review2 = review2_database_health()
        healthy = database.get("connected", False) and (not review2["configured"] or review2["connected"])
        return jsonify(status="ok" if healthy else "error", backend="running", database=database, review2_database=review2), (200 if healthy else 503)

    def token_required(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            try: request.user = jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
            except jwt.ExpiredSignatureError: return jsonify(error="Your session has expired. Sign in again."), 401
            except jwt.PyJWTError: return jsonify(error="Authentication required"), 401
            return fn(*args, **kwargs)
        return wrapped
    def issue(user: dict) -> str:
        claims = {"id": user["id"], "email": user["email"], "role": user["role"], "exp": datetime.now(timezone.utc) + TOKEN_LIFETIME}
        for key in ("portal", "institution", "hospital_id"):
            if user.get(key) is not None: claims[key] = user[key]
        return jwt.encode(claims, app.config["SECRET_KEY"], algorithm="HS256")
    def profile_for(user: dict) -> dict:
        with connection() as db:
            profile = db.execute("SELECT portal,institution,hospital_id FROM partner_profiles WHERE user_id=?", (user["id"],)).fetchone()
        return {**user, **(dict(profile) if profile else {})}
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
    @app.post("/api/auth/register")
    def register():
        data = request.get_json() or {}; name, email, password = data.get("name", ""), data.get("email", "").lower(), data.get("password", "")
        role = data.get("role", "citizen") if data.get("role") in {"citizen", "volunteer", "responder"} else "citizen"
        if not name or "@" not in email or len(password) < 6: return jsonify(error="Provide a name, valid email, and password of 6+ characters"), 400
        try:
            with connection() as db:
                cur = db.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", (name, email, generate_password_hash(password), role)); user = dict(db.execute("SELECT id,name,email,role FROM users WHERE id=?", (cur.lastrowid,)).fetchone())
        except Exception as error:
            if is_integrity_error(error):
                return jsonify(error="Email is already registered. Sign in with this address or register a different one."), 409
            app.logger.exception("Account registration failed")
            return jsonify(error="Registration is temporarily unavailable. Check the database connection and try again."), 503
        return jsonify(token=issue(user), user=user), 201
    @app.post("/api/auth/login")
    def login():
        data = request.get_json() or {}
        with connection() as db: row = db.execute("SELECT * FROM users WHERE email=?", (data.get("email", "").lower(),)).fetchone()
        if not row or not check_password_hash(row["password"], data.get("password", "")): return jsonify(error="Invalid credentials"), 401
        user = profile_for({k: row[k] for k in ("id", "name", "email", "role")})
        return jsonify(token=issue(user), user=user)
    @app.post("/api/admin/partner-accounts")
    @token_required
    @role_required("admin")
    def create_partner_account():
        data = request.get_json() or {}
        name = str(data.get("name", "")).strip()
        email = str(data.get("email", "")).strip().lower()
        password = str(data.get("password", ""))
        portal = str(data.get("portal", ""))
        institution = str(data.get("institution", "")).strip()
        hospital_id = data.get("hospital_id")
        roles = {"ngo": "volunteer", "dispatch": "official", "hospital": "volunteer"}
        if portal not in roles or not name or "@" not in email or len(password) < 10 or not institution:
            return jsonify(error="Enter an organisation, name, valid email, and password of at least 10 characters."), 400
        if portal == "hospital":
            try: hospital_id = int(hospital_id)
            except (TypeError, ValueError): return jsonify(error="Select the hospital this account will manage."), 400
        else:
            hospital_id = None
        try:
            with connection() as db:
                if hospital_id is not None and not db.execute("SELECT 1 FROM hospitals WHERE id=?", (hospital_id,)).fetchone():
                    return jsonify(error="The selected hospital does not exist."), 400
                cur = db.execute("INSERT INTO users(name,email,password,role) VALUES(?,?,?,?)", (name, email, generate_password_hash(password), roles[portal]))
                user_id = cur.lastrowid
                db.execute("INSERT INTO partner_profiles(user_id,portal,institution,hospital_id) VALUES(?,?,?,?)", (user_id, portal, institution, hospital_id))
                db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "PARTNER_ACCOUNT_CREATED", email, f"Provisioned {portal} access for {institution}"))
        except Exception as error:
            if is_integrity_error(error): return jsonify(error="That email address already has an account."), 409
            app.logger.exception("Partner account provisioning failed")
            return jsonify(error="Could not create the partner account."), 503
        user = {"id": user_id, "name": name, "email": email, "role": roles[portal], "portal": portal, "institution": institution, "hospital_id": hospital_id}
        return jsonify(user=user, message="Partner account created. The user can now sign in through the matching portal."), 201
    @app.post("/api/missions/claim")
    @token_required
    @role_required("admin", "official")
    def claim_mission():
        data = request.get_json() or {}; report_id, team = data.get("reportId", "").strip(), data.get("team", "").strip()
        hospital_id = data.get("hospitalId")
        if not report_id or not team: return jsonify(error="Report ID and rescue team are required"), 400
        try:
            with connection() as db:
                team_row = db.execute("SELECT id,availability FROM rescue_teams WHERE name=?", (team,)).fetchone()
                if not team_row: return jsonify(error="Choose a rescue team registered in DMERS"), 400
                if team_row["availability"] != "available": return jsonify(error="That rescue team is not currently available"), 409
                if hospital_id is not None:
                    hospital = db.execute("SELECT id,status,available_beds FROM hospitals WHERE id=?", (hospital_id,)).fetchone()
                    if not hospital or hospital["status"] == "divert" or hospital["available_beds"] < 1: return jsonify(error="Choose a receiving hospital that is accepting transfers and has capacity."), 409
                incident = db.execute("SELECT id FROM incidents WHERE reference=?", (report_id,)).fetchone()
                cur = db.execute("INSERT INTO missions(incident_id,report_id,team_name,team_id,hospital_id,assigned_by) VALUES(?,?,?,?,?,?)", (incident["id"] if incident else None, report_id, team, team_row["id"], hospital_id, request.user["id"])); mission_id = cur.lastrowid
                db.execute("UPDATE rescue_teams SET availability='deployed' WHERE id=?", (team_row["id"],))
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
            db.execute("UPDATE missions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, mission_id))
            if status in {"completed", "aborted"} and mission["team_id"]:
                db.execute("UPDATE rescue_teams SET availability='available' WHERE id=?", (mission["team_id"],))
            db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "MISSION_STATUS", mission["report_id"], f"Mission {mission_id} changed to {status}"))
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
    def routing_options(data: dict) -> tuple[str, str, str]:
        return (str(data.get("algorithm", "astar")).lower(), str(data.get("mode", "fastest")).lower(), str(data.get("weather", "clear")).lower())

    @app.post("/api/map/route")
    def map_route():
        """Route through stops on the real OpenStreetMap road graph, honouring closures and hazard risk."""
        data = request.get_json(silent=True) or {}
        try:
            stops = data.get("stops") or [data["start"], data["end"]]
            if not road_network.graph_available():
                if len(stops) < 2 or not all(isinstance(point, list) and len(point) == 2 for point in stops):
                    raise ValueError("Provide at least two stops as [latitude, longitude]")
                points = [[float(point[0]), float(point[1])] for point in stops]
                total = sum(road_network.haversine_m(tuple(points[i]), tuple(points[i + 1])) for i in range(len(points) - 1))
                return jsonify(points=points, stops=points, distanceMeters=round(total, 1), durationSeconds=round(total / 8.33, 1), source="straight-line", offline=True)
            algorithm, mode, weather = routing_options(data)
            return jsonify(road_network.route_stops(stops, data.get("hazards"), algorithm, mode, weather))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error) or "Provide stops as [latitude, longitude]"), 400

    @app.post("/api/map/compare-algorithms")
    def map_compare_algorithms():
        """Run BFS, DFS, UCS, Greedy and A* on the same real road query and report honest metrics."""
        data = request.get_json(silent=True) or {}
        try:
            _, mode, weather = routing_options(data)
            return jsonify(road_network.compare_algorithms(data["start"], data["goal"], data.get("hazards"), mode, weather))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error) or "Provide start and goal as [latitude, longitude]"), 400

    @app.post("/api/map/mission-plan")
    def map_mission_plan():
        """Order victims, pick receiving hospitals by routed cost, and draw the real-road tour."""
        data = request.get_json(silent=True) or {}
        try:
            algorithm, mode, weather = routing_options({"mode": "balanced", **data})
            return jsonify(road_network.plan_missions(data["team"], data["victims"], data["hospitals"], data.get("hazards"), algorithm, mode, weather))
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error) or "Provide team, victims and hospitals"), 400

    @app.get("/api/map/coverage")
    def map_coverage():
        if not road_network.graph_available():
            return jsonify(available=False)
        g = road_network.graph()
        return jsonify(available=True, bbox=g.meta["bbox"], nodes=len(g.lat), road_segments=g.edge_count // 2, attribution=g.meta["attribution"],
                       built=g.meta["built"], hazard_types={k: v["label"] for k, v in road_network.HAZARD_PROFILES.items()},
                       weather={k: v[2] for k, v in road_network.WEATHER.items()}, algorithms=road_network.ALGORITHM_NOTES)

    @app.get("/api/map/facilities")
    def map_facilities():
        """Real hospitals, fire stations, police stations and shelters bundled from OpenStreetMap."""
        path = road_network.DATA_PATH.with_name("vellore_facilities.json")
        if not path.exists():
            return jsonify(facilities=[], attribution=None)
        import json
        with path.open(encoding="utf-8") as handle:
            return jsonify(json.load(handle))
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

    @app.get("/api/data/relationships")
    @token_required
    def data_relationships():
        """Return a real mission → incident → location/team/hospital join."""
        with connection() as db:
            rows = [dict(row) for row in db.execute("""
                SELECT m.id AS mission_id, m.status AS mission_status, m.created_at AS mission_created_at,
                       i.reference AS incident_reference, i.disaster_type, i.severity, i.status AS incident_status,
                       l.label AS incident_location, COALESCE(rt.name,m.team_name) AS team_name, h.name AS hospital_name,
                       m.hospital_id AS hospital_id
                FROM missions m
                LEFT JOIN incidents i ON i.id=m.incident_id
                LEFT JOIN locations l ON l.id=i.location_id
                LEFT JOIN rescue_teams rt ON rt.id=m.team_id
                LEFT JOIN hospitals h ON h.id=m.hospital_id
                ORDER BY m.created_at DESC LIMIT 50
            """)]
            audit_rows = [dict(row) for row in db.execute("""
                SELECT a.id,a.action,a.subject,a.details,a.created_at,u.name AS actor_name
                FROM audit_entries a LEFT JOIN users u ON u.id=a.actor_id
                ORDER BY a.id DESC LIMIT 25
            """)]
        return jsonify(missions=rows, audit=audit_rows)

    @app.get("/api/data/tables")
    @token_required
    def data_tables():
        # Explicit allow-list avoids exposing credentials or arbitrary schema internals.
        with connection() as db:
            tables = []
            for name in ("roles", "users", "locations", "incidents", "rescue_teams", "hospitals", "missions", "simulations", "audit_entries"):
                metadata = db.table_info(name)
                columns = [row["column_name"] if using_postgres() else row[1] for row in metadata]
                tables.append({"name": name, "columns": columns, "count": db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]})
        return jsonify(tables=tables)

    def engine_name() -> str:
        return "PostgreSQL" if using_postgres() else "SQLite (offline)"

    def csv_response(body: str, name: str, subject: str):
        audit(request.user["id"], "DATA_EXPORTED", subject, f"{name} downloaded")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        return Response(body, mimetype="text/csv", headers={"Content-Disposition": f'attachment; filename="{name}-{stamp}.csv"', "Cache-Control": "no-store"})

    @app.get("/api/data/schema")
    @token_required
    @role_required("admin", "official")
    def data_schema():
        """Live data dictionary, relationships and constraints for on-screen review."""
        with connection() as db:
            return jsonify(engine=engine_name(), dictionary=schema_export.dictionary(db), relationships=schema_export.relationships(db), constraints=schema_export.constraints_report(db))

    @app.get("/api/data/schema.csv")
    @token_required
    @role_required("admin", "official")
    def data_schema_csv():
        with connection() as db: body = schema_export.to_csv(schema_export.dictionary(db))
        return csv_response(body, "dmers-schema-dictionary", "schema dictionary")

    @app.get("/api/data/relationships.csv")
    @token_required
    @role_required("admin", "official")
    def data_relationships_csv():
        with connection() as db: body = schema_export.to_csv(schema_export.relationships(db))
        return csv_response(body, "dmers-relationships", "relationships")

    @app.get("/api/data/constraints.csv")
    @token_required
    @role_required("admin", "official")
    def data_constraints_csv():
        with connection() as db: body = schema_export.to_csv(schema_export.constraints_report(db))
        return csv_response(body, "dmers-constraints", "constraints")

    @app.get("/api/data/export.csv")
    @token_required
    @role_required("admin", "official")
    def data_table_csv():
        table = request.args.get("table", "")
        if table not in schema_export.TABLES: return jsonify(error="Choose one of: " + ", ".join(schema_export.TABLES)), 400
        with connection() as db: body = schema_export.to_csv(schema_export.table_rows(db, table))
        return csv_response(body, f"dmers-{table}", f"table {table}")

    @app.get("/api/data/bundle.zip")
    @token_required
    @role_required("admin", "official")
    def data_bundle():
        with connection() as db: payload = schema_export.bundle(db, engine_name())
        audit(request.user["id"], "DATA_EXPORTED", "full bundle", "ZIP with schema dictionary, relationships, constraints and table data")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        return Response(payload, mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="dmers-database-export-{stamp}.zip"', "Cache-Control": "no-store"})

    @app.get("/api/review2/overview")
    @token_required
    def review2_overview():
        try:
            with review2_connection() as db:
                table_names = ("users", "zones", "incidents", "response_units", "resources", "incident_updates", "dispatches", "resource_allocations")
                counts = {name: db.execute(f"SELECT COUNT(*) AS count FROM {name}").fetchone()["count"] for name in table_names}
                zones = [dict(row) for row in db.execute("SELECT * FROM v_zone_situation ORDER BY active_incidents DESC, zone_name")]
                incidents = [dict(row) for row in db.execute("""
                    SELECT i.id, i.title, i.incident_type, i.severity, i.status, i.location,
                           z.zone_name, i.created_at, fn_response_minutes(i.id)::DOUBLE PRECISION AS response_minutes
                    FROM incidents i LEFT JOIN zones z ON z.id=i.zone_id
                    ORDER BY CASE i.status WHEN 'RESPONDING' THEN 0 WHEN 'VERIFIED' THEN 1 ELSE 2 END,
                             CASE i.severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MODERATE' THEN 2 ELSE 3 END,
                             i.created_at DESC LIMIT 12
                """)]
                resources = [dict(row) for row in db.execute("SELECT id, resource_name, category, quantity_available, reorder_level, fn_stock_status(id) AS stock_status FROM resources ORDER BY CASE fn_stock_status(id) WHEN 'OUT_OF_STOCK' THEN 0 WHEN 'LOW' THEN 1 ELSE 2 END, resource_name")]
                units = [dict(row) for row in db.execute("""
                    SELECT r.id, r.unit_name, r.unit_type, r.availability_status, r.personnel_count,
                           z.zone_name, u.full_name AS unit_lead
                    FROM response_units r JOIN zones z ON z.id=r.zone_id
                    LEFT JOIN users u ON u.id=r.lead_user_id
                    ORDER BY r.availability_status, r.unit_name
                """)]
                timeline = [dict(row) for row in db.execute("""
                    SELECT u.incident_id, i.title, u.update_no, u.previous_status, u.new_status,
                           u.note, u.logged_at, a.full_name AS logged_by
                    FROM incident_updates u JOIN incidents i ON i.id=u.incident_id
                    LEFT JOIN users a ON a.id=u.logged_by
                    ORDER BY u.logged_at DESC, u.incident_id DESC, u.update_no DESC LIMIT 14
                """)]
            return jsonify(counts=counts, zones=zones, incidents=incidents, resources=resources, units=units, timeline=timeline)
        except Exception:
            app.logger.exception("Review II database read failed")
            return jsonify(error="Review II database is unavailable or its SQL demo has not been initialized."), 503

    @app.get("/api/incidents")
    @token_required
    def list_incidents():
        with connection() as db:
            rows = [dict(row) for row in db.execute("SELECT i.*,l.label AS location,l.latitude,l.longitude,u.name AS reporter FROM incidents i JOIN locations l ON l.id=i.location_id LEFT JOIN users u ON u.id=i.reported_by ORDER BY i.created_at DESC")]
        return jsonify(incidents=rows)

    @app.post("/api/public/reports")
    def public_report():
        """Anonymous, limited-scope intake; reports remain pending for review."""
        data = request.get_json(silent=True) or {}
        allowed_types = {"Medical emergency", "Fire", "Flooding", "Road blockage", "Trapped or missing person", "Structural damage", "Shelter or relief", "Other"}
        kind = str(data.get("kind", "")).strip()
        description = str(data.get("description", "")).strip()
        location = data.get("location") if isinstance(data.get("location"), dict) else {}
        label = str(location.get("label", "")).strip()
        if kind not in allowed_types:
            return jsonify(error="Choose a listed incident type"), 400
        if len(description) < 10 or len(description) > 2000:
            return jsonify(error="Describe what happened in 10 to 2000 characters"), 400
        if len(label) < 3 or len(label) > 160:
            return jsonify(error="Provide a location between 3 and 160 characters"), 400
        latitude = location.get("latitude")
        longitude = location.get("longitude")
        if (latitude is None) != (longitude is None):
            return jsonify(error="Provide both coordinates or leave both blank"), 400
        try:
            if latitude is not None:
                latitude, longitude = float(latitude), float(longitude)
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError("Coordinates are outside valid latitude/longitude bounds")
        except (TypeError, ValueError) as error:
            return jsonify(error=str(error) or "Coordinates must be numeric"), 400

        severity = "critical" if data.get("immediate_danger") is True else "high"
        reference = f"PUB-{random.randint(100000, 999999)}"
        try:
            with connection() as db:
                place_id = db.execute("INSERT INTO locations(label,latitude,longitude) VALUES(?,?,?)", (label, latitude, longitude)).lastrowid
                incident_id = db.execute(
                    "INSERT INTO incidents(reference,disaster_type,severity,status,description,location_id,reported_by) VALUES(?,?,?,'reported',?,?,NULL)",
                    (reference, kind, severity, description, place_id),
                ).lastrowid
                db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(NULL,?,?,?)", ("PUBLIC_REPORT_RECEIVED", reference, f"Anonymous public report; priority self-reported as {'immediate danger' if severity == 'critical' else 'not immediate'}; awaiting authorised review"))
            return jsonify(reference=reference, incident_id=incident_id, state="pending_review", message="Your report was received. An authorised DMERS operator must verify it before operational action."), 201
        except Exception:
            app.logger.exception("Anonymous public incident intake failed")
            return jsonify(error="The report could not be saved right now. Please retry or contact local emergency services directly."), 503

    @app.post("/api/ai/assess")
    @token_required
    def ai_assess_incident():
        """Return an explainable, read-only advisory from persisted DMERS facts."""
        data = request.get_json() or {}
        try:
            incident_id = int(data.get("incident_id"))
        except (TypeError, ValueError):
            return jsonify(error="Provide a valid incident_id"), 400
        with connection() as db:
            incident_row = db.execute("""
                SELECT i.id,i.reference,i.disaster_type,i.severity,i.status,i.description,
                       l.label AS location,l.latitude,l.longitude
                FROM incidents i JOIN locations l ON l.id=i.location_id WHERE i.id=?
            """, (incident_id,)).fetchone()
            if not incident_row:
                return jsonify(error="Incident not found"), 404
            teams = [dict(row) for row in db.execute("""
                SELECT t.id,t.name,t.capability,t.availability,
                       COUNT(m.id) AS active_missions
                FROM rescue_teams t
                LEFT JOIN missions m ON m.team_id=t.id AND m.status NOT IN ('completed','aborted')
                GROUP BY t.id,t.name,t.capability,t.availability
            """)]
            hospitals = [dict(row) for row in db.execute("""
                SELECT h.id,h.name,h.total_beds,h.available_beds,h.status,l.label AS location
                FROM hospitals h LEFT JOIN locations l ON l.id=h.location_id
            """)]
        return jsonify(build_advisory(dict(incident_row), teams, hospitals))

    @app.post("/api/ai/route-plan")
    @token_required
    @role_required("admin", "official")
    def ai_route_plan():
        """Create a multi-target, risk-aware route proposal; never dispatches."""
        data = request.get_json() or {}
        try:
            grid = data["grid"]
            start = tuple(data["start"])
            targets = [tuple(point) for point in data["targets"]]
            advisory = plan_response_route(
                grid, start, targets, data.get("mode", "auto"),
                int(data.get("available_units", 1)), str(data.get("severity", "moderate")).lower(),
            )
            return jsonify(advisory)
        except (KeyError, TypeError, ValueError) as error:
            return jsonify(error=str(error)), 400

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
        except Exception as error:
            app.logger.exception("Incident persistence failed")
            if is_integrity_error(error):
                return jsonify(error="Incident could not be saved because a referenced record or unique reference is invalid"), 409
            return jsonify(error="Incident could not be saved because the database operation failed"), 503

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
        with connection() as db:
            if request.user.get("portal") == "hospital":
                rows=[dict(row) for row in db.execute("SELECT h.*,l.label AS location FROM hospitals h LEFT JOIN locations l ON l.id=h.location_id WHERE h.id=? ORDER BY available_beds DESC", (request.user.get("hospital_id"),))]
            else:
                rows=[dict(row) for row in db.execute("SELECT h.*,l.label AS location FROM hospitals h LEFT JOIN locations l ON l.id=h.location_id ORDER BY available_beds DESC")]
        return jsonify(hospitals=rows)
    @app.get("/api/hospitals/<int:hospital_id>/transfers")
    @token_required
    def hospital_transfers(hospital_id: int):
        if request.user.get("role") != "admin" and not (request.user.get("portal") == "hospital" and request.user.get("hospital_id") == hospital_id):
            return jsonify(error="Only this hospital's verified account or an administrator can view its assigned transfers."), 403
        with connection() as db:
            rows = [dict(row) for row in db.execute("""
                SELECT m.id AS mission_id,m.status AS mission_status,m.report_id AS incident_reference,
                       i.disaster_type,i.severity,l.label AS incident_location,COALESCE(rt.name,m.team_name) AS team_name,
                       m.created_at
                FROM missions m LEFT JOIN incidents i ON i.id=m.incident_id
                LEFT JOIN locations l ON l.id=i.location_id
                LEFT JOIN rescue_teams rt ON rt.id=m.team_id
                WHERE m.hospital_id=? ORDER BY m.created_at DESC LIMIT 100
            """, (hospital_id,))]
        return jsonify(transfers=rows)
    @app.patch("/api/hospitals/<int:hospital_id>/capacity")
    @token_required
    def update_hospital_capacity(hospital_id: int):
        if request.user.get("role") != "admin" and not (request.user.get("portal") == "hospital" and request.user.get("hospital_id") == hospital_id):
            return jsonify(error="Only this hospital's verified account or an administrator can update its capacity."), 403
        data = request.get_json() or {}
        try:
            total = int(data.get("total_beds")); available = int(data.get("available_beds"))
        except (TypeError, ValueError): return jsonify(error="Bed counts must be whole numbers."), 400
        status = data.get("status")
        if total < 0 or available < 0 or available > total or status not in {"accepting", "limited", "divert"}:
            return jsonify(error="Provide valid bed counts and an accepting, limited, or divert status."), 400
        with connection() as db:
            hospital = db.execute("SELECT name FROM hospitals WHERE id=?", (hospital_id,)).fetchone()
            if not hospital: return jsonify(error="Hospital not found."), 404
            db.execute("UPDATE hospitals SET total_beds=?,available_beds=?,status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (total, available, status, hospital_id))
            db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "HOSPITAL_CAPACITY_UPDATED", hospital["name"], f"{available}/{total} beds available; status={status}"))
            row = db.execute("SELECT id,name,total_beds,available_beds,status,updated_at FROM hospitals WHERE id=?", (hospital_id,)).fetchone()
        return jsonify(hospital=dict(row))
    @app.post("/api/hospitals/missions/<int:mission_id>/receive")
    @token_required
    def hospital_receive_mission(mission_id: int):
        if request.user.get("role") != "admin" and request.user.get("portal") != "hospital":
            return jsonify(error="A verified hospital portal account is required."), 403
        with connection() as db:
            mission = db.execute("SELECT id,hospital_id,status,report_id FROM missions WHERE id=?", (mission_id,)).fetchone()
            if not mission: return jsonify(error="Transfer not found."), 404
            if request.user.get("role") != "admin" and mission["hospital_id"] != request.user.get("hospital_id"):
                return jsonify(error="This transfer is assigned to another hospital."), 403
            if mission["status"] not in {"assigned", "acknowledged", "en_route", "on_scene", "in_progress"}:
                return jsonify(error="This transfer cannot be marked received from its current state."), 409
            db.execute("UPDATE missions SET status='at_hospital',updated_at=CURRENT_TIMESTAMP WHERE id=?", (mission_id,))
            db.execute("INSERT INTO audit_entries(actor_id,action,subject,details) VALUES(?,?,?,?)", (request.user["id"], "HOSPITAL_TRANSFER_RECEIVED", mission["report_id"] or f"Mission {mission_id}", f"Hospital {mission['hospital_id']} confirmed transfer receipt"))
        return jsonify(id=mission_id,status="at_hospital")
    return app

if __name__ == "__main__": create_app().run(debug=True, port=5000)
