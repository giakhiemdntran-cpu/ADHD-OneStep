#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export ONESTEP_API_URL="${ONESTEP_API_URL:-http://127.0.0.1:5000}"
export ONESTEP_ADMIN_PORT="${ONESTEP_ADMIN_PORT:-8501}"
exec python khoi_dong_quan_tri.py
