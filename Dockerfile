FROM python:3.12-slim

# git is required by GitPython for the publish flow
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /app/content is mounted as a volume so content.json and PDFs persist
# /app/live-site is mounted as a volume for the live GitHub Pages repo clone
VOLUME ["/app/content", "/app/live-site"]

# Admin UI on 5000, preview server on 5050
EXPOSE 5000 5050

# 1 worker + 4 threads: threading.Lock works correctly within a single process,
# and 4 threads means PDF rendering / slow uploads don't block the UI.
CMD ["gunicorn", \
     "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "300", \
     "--chdir", "/app/admin", \
     "app:app"]
