#!/bin/sh
set -e

echo "Starting embedded Redis server..."
redis-server --daemonize yes --bind 127.0.0.1 --port 6379

echo "Starting Dhan Redis Hub FastAPI server..."
exec uvicorn app:app --host 0.0.0.0 --port 8080
