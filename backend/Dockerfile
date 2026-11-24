# APIForge AI Backend Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ app/
COPY samples/ samples/

EXPOSE 8000

ENV DATABASE_URL=sqlite:///./apiforge.db
ENV OLLAMA_URL=http://host.docker.internal:11434
ENV CHAT_MODEL=qwen2.5:7b-instruct
ENV EMBED_MODEL=nomic-embed-text
ENV JWT_SECRET=apiforge-super-secret-jwt-key-change-in-production-min-32-chars
ENV FERNET_KEY=J6Q20w8l6l_vG2g7yXJ1T-0t0lY9L8A2k8g7h5d4s3E=
ENV DEBUG=True
ENV DEV_ALLOWED_HOSTS=localhost,127.0.0.1,host.docker.internal

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
