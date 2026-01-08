````markdown
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
````

### 2) Install dependencies

```bash
pip install -U pip
pip install opencv-python pyvirtualcam flask
```

> Tip: On some Linux systems you may prefer `opencv-python-headless` if you don’t need GUI windows:
> `pip install opencv-python-headless`

---

## Linux setup (v4l2loopback)

If you want the virtual camera to appear as a standard V4L2 device:

### Install `v4l2loopback`

(Example: Arch)

```bash
sudo pacman -S v4l2loopback-dkms
```

(Example: Debian/Ubuntu)

```bash
sudo apt-get update
sudo apt-get install v4l2loopback-dkms
```

### Load module

```bash
sudo modprobe v4l2loopback video_nr=0 card_label="FaceCam" exclusive_caps=1
```

Verify:

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

> This project assumes `/dev/video0` is the FaceCam output on Linux and intentionally skips index `0` for input probing.

---

## Run

```bash
python facecam.py
```

Then open the control UI:

* [http://127.0.0.1:5000](http://127.0.0.1:5000)

In Zoom/Meet/Teams:

* Select the **virtual camera** device (often labeled `FaceCam` on Linux with v4l2loopback, or whatever backend provides on your OS).

---

## Controls (UI)

### Camera

Pick the physical camera index to use as the input source.

### Orientation

* **No rotation**
* **90° clockwise**
* **90° counter-clockwise**

Useful for phone-as-webcam setups or rotated camera mounts.

### Face Tracking

* **Detection every N frames**
  Higher = less CPU usage, slower to react to movement.
* **Smoothing alpha**
  Lower = smoother (less jitter), more lag.
* **Margin factor**
  Higher = looser framing (keeps more background, moves less aggressively).

---

## Configuration

Config is stored in:

* `facecam_config.json`

Defaults:

* `camera_index`: `null` (auto-picks first available via UI logic)
* `orientation`: `"none"`
* `detection_every_n_frames`: `10`
* `smoothing_alpha`: `0.02`
* `margin_factor`: `2.8`

Logs:

* `facecam.log`

---

## API

### `GET /api/config`

Returns current config.

### `POST /api/config`

Update one or more fields:

```json
{
  "camera_index": 1,
  "orientation": "cw",
  "detection_every_n_frames": 10,
  "smoothing_alpha": 0.02,
  "margin_factor": 2.8
}
```

### `GET /api/cameras`

Returns detected input camera indices.

---

## Troubleshooting

### No cameras detected

* Ensure your camera is not blocked by another app.
* On Linux, check permissions:

  ```bash
  ls -l /dev/video*
  groups
  ```

  You may need to be in the `video` group:

  ```bash
  sudo usermod -aG video $USER
  ```

### Virtual camera not showing up (Linux)

* Confirm `v4l2loopback` is loaded:

  ```bash
  lsmod | grep v4l2loopback
  ```
* Confirm `/dev/video0` exists and is the loopback device.

### High CPU usage

* Increase **Detection every N frames**
* Increase **Margin factor** slightly (reduces motion sensitivity)
* Consider lowering input resolution (inside the code) if needed

### Face detection is laggy/jittery

* Reduce **Detection every N frames** (more frequent detection)
* Increase **Smoothing alpha** slightly (less lag, more jitter)
* Decrease **Smoothing alpha** (more smooth, more lag) if jitter is the issue

---

## Security Notes

* The Flask server binds to **127.0.0.1** (local machine only).
* No authentication is implemented; do not expose it publicly.

---

## Roadmap / Ideas

* Replace Haar cascades with a faster/more accurate detector (e.g., MediaPipe)
* Add face selection when multiple faces are detected
* Add a preview stream endpoint for debugging
* Package as a systemd service (Linux) / tray app (Windows)

---

## License

Choose a license (MIT/Apache-2.0/etc.) and add a `LICENSE` file.

---

## Credits

* OpenCV Haar cascades for face detection
* `pyvirtualcam` for cross-platform virtual camera output
* Flask for the control UI + API

```
```
