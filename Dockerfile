# Minimal image: the bot is stdlib-only, so nothing needs installing.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

WORKDIR /app

# No dependencies to copy or install; copy sources last for layer caching.
COPY *.py ./

# Non-root user; the volume at /data must be writable by it.
RUN useradd -m -u 10001 rix && mkdir -p /data && chown -R rix /data /app
USER rix

EXPOSE 8080

CMD ["python", "bot.py"]
