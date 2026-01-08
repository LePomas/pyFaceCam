# pyFaceCam

A lightweight **Python virtual webcam** that **auto-crops a square frame around your face** (with smoothing to reduce jitter) and outputs it to a **virtual camera** so you can select it in **Zoom / Google Meet / Teams / OBS**.

It also includes a simple **Flask web UI** (local-only) to change settings at runtime:
- Select input camera
- Rotate orientation (none / 90° cw / 90° ccw)
- Tune face detection frequency, smoothing, and framing margin

---

## Features

- ✅ Real-time face detection + square auto-crop (no aspect distortion)
- ✅ **Virtual camera output** via `pyvirtualcam`
- ✅ **Local web UI** to control settings without restarting the stream
- ✅ Config persistence (`facecam_config.json`)
- ✅ Structured logging to file + console (`facecam.log`)
- ✅ Linux safety: skips `/dev/video0` as input (commonly used by `v4l2loopback`)

---

## How it works (high level)

1. OpenCV captures frames from your selected physical camera.
2. Face detection runs every **N frames** (configurable) using Haar cascades.
3. Face center + size are smoothed over time to reduce jitter.
4. A **square crop** is computed around the smoothed face position, expanded by a **margin factor**.
5. The crop is resized to **640×640 @ 30 FPS** and sent to a virtual camera.
6. A Flask server exposes:
   - `GET /` (control UI)
   - `GET /api/config` and `POST /api/config`
   - `GET /api/cameras`

---

## Requirements

- Python 3.9+ recommended
- OS:
  - **Linux**: `v4l2loopback` recommended (virtual camera device at `/dev/video0`)
  - **Windows/macOS**: `pyvirtualcam` will use an available backend (often OBS Virtual Camera)

Python packages:
- `opencv-python`
- `pyvirtualcam`
- `flask`

---

## Install

### 1) Create a virtual environment
```bash
python -m venv .venv
source .venv/bin/activate
# Windows (PowerShell):
# .\.venv\Scripts\Activate.ps1
