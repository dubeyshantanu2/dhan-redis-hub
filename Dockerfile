FROM python:3.11-slim

# Install redis-server
RUN apt-get update && apt-get install -y --no-install-recommends redis-server && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port
EXPOSE 8080

RUN chmod +x start.sh

CMD ["./start.sh"]
