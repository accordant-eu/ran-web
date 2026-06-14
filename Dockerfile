FROM python:3.12-slim

# Install gosu for clean privilege dropping (su-exec equivalent for Debian)
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd --create-home --shell /bin/bash --uid 1000 ran

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and entrypoint
COPY backend/main.py .
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create mount points with correct ownership
RUN mkdir -p /app/data /app/prompts && chown -R ran:ran /app/data /app/prompts

EXPOSE 8000

# Start as root so entrypoint can fix bind-mount permissions, then drop to ran
ENTRYPOINT ["docker-entrypoint.sh"]
# Two workers: each handles one concurrent Anthropic stream (sync in thread).
# fcntl.LOCK_EX in codes_lock() is process-safe, so multi-worker is safe.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
