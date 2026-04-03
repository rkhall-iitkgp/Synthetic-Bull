FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install bot requirements
COPY bots/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy and install the Python SDK
COPY sdk/python /tmp/sdk
RUN pip install --no-cache-dir /tmp/sdk && rm -rf /tmp/sdk

# Copy bot source code
COPY bots/ .

EXPOSE 3001 3002

CMD ["python", "-m", "alpha.main"]