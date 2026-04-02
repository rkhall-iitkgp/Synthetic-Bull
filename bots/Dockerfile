FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The CMD is overridden in docker-compose.yml, but we can set a default
CMD ["python", "-m", "alpha.main"]
