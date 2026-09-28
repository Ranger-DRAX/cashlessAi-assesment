#!/bin/sh
set -e

echo "Applying database migrations..."
python manage.py migrate --no-input

echo "Starting server on 0.0.0.0:8000..."
exec "$@"
