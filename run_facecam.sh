#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Linux-only: ensure v4l2loopback is loaded
if [ "$(uname)" = "Linux" ]; then
  if ! lsmod | grep -q v4l2loopback; then
    echo "[facecam] v4l2loopback not loaded, trying: sudo modprobe v4l2loopback"
    sudo modprobe v4l2loopback || {
      echo "[facecam] Failed to load v4l2loopback. Install it first (v4l2loopback-dkms)."
    }
  fi
fi

if [ ! -d "$SCRIPT_DIR/.venv" ]; then
  echo "[facecam] Creating virtual environment..."
  python -m venv "$SCRIPT_DIR/.venv"
  echo "[facecam] Installing dependencies..."
  "$SCRIPT_DIR/.venv/bin/python" -m pip install --upgrade pip
  "$SCRIPT_DIR/.venv/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"
fi

echo "[facecam] Starting..."
"$SCRIPT_DIR/.venv/bin/python" "$SCRIPT_DIR/main.py"
