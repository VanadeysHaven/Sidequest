FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY pyproject.toml README.md alembic.ini ./
COPY src/ src/
COPY migrations/ migrations/
RUN pip install --no-deps --no-cache-dir .

# Run as an unprivileged user
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin sidequest
USER sidequest

# Healthy while the reminder loop keeps writing its heartbeat (every <= 60 s).
# start-period covers migrations, login and the first loop iteration.
HEALTHCHECK --interval=60s --timeout=10s --start-period=120s --retries=3 \
    CMD ["sidequest", "healthcheck"]

CMD ["sidequest"]
