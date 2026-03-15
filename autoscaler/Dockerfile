FROM python:3.11-slim

WORKDIR /code

# Install build dependencies needed for psutil compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./autoscaler

RUN adduser --disabled-password --gecos "" autoscaler
USER autoscaler

# Port 9091 exposes self-metrics to Prometheus
EXPOSE 9091

CMD ["python", "-m", "autoscaler.main"]
