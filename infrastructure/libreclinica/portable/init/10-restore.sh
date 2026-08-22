#!/bin/sh
set -eu

seed_path=/seed/libreclinica-portable-synthetic.dump
if [ ! -f "$seed_path" ]; then
    echo "Portable LibreClinica seed is missing." >&2
    exit 1
fi

pg_restore \
    --exit-on-error \
    --no-owner \
    --no-privileges \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    "$seed_path"
