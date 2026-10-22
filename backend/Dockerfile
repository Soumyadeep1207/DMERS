FROM python:3.12-slim AS production

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN addgroup --system app && adduser --system --ingroup app app
COPY --chown=app:app run.py ./run.py
COPY --chown=app:app app ./app
COPY --chown=app:app db ./db
COPY --chown=app:app ai ./ai
COPY --chown=app:app migrations ./migrations

USER app
EXPOSE 5000
CMD ["gunicorn", "--preload", "--workers", "2", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "--bind", "0.0.0.0:5000", "run:app"]

FROM python:3.12-slim AS development

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY run.py ./run.py
COPY app ./app
COPY db ./db
COPY ai ./ai
COPY migrations ./migrations
EXPOSE 5000
CMD ["python", "-m", "flask", "--app", "run", "run", "--debug", "--host", "0.0.0.0", "--port", "5000"]
