# Installation Guide

## Prerequisites

Install Python 3.10+ and Node.js 20+. SQLite is included with Python. Use PowerShell on Windows.

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SECRET_KEY = 'a-long-random-production-secret'
flask --app run run --debug
```

The first start creates `backend/disaster_response.db` and its sample administrator.

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

The Vite console prints the local URL. For production, run `npm run build`, serve `frontend/dist`, and configure the API origin in `src/main.jsx` or put both behind a reverse proxy.

## Validation

Run `python -m pytest backend/tests` after installing pytest, then `npm run build` in `frontend`. In production, replace the development secret, narrow CORS origins, use HTTPS, and run Flask with a production WSGI server.
