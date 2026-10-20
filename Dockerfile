# Minimal image: the bot is stdlib-only, so nothing needs installing.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

# No dependencies to copy or install; copy sources last for layer caching.
COPY *.py ./

# Railway mounts volumes root-owned, so a non-root USER here caused
# PermissionError on /data at boot. Run as root; config.ensure_dirs() still
# falls back safely if a path is ever unwritable.
RUN mkdir -p /data

EXPOSE 8080

CMD ["python", "bot.py"]
