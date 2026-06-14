FROM python:3.12-slim

# Create non-root user
RUN useradd --create-home --shell /bin/bash ran

WORKDIR /app

# Install dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/main.py .

# Run as non-root
USER ran

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
