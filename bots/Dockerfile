FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: override CMD in docker-compose per bot
CMD ["python", "-m", "alpha.main"]
