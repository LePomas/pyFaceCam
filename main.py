#!/usr/bin/env python3
import threading
import time
import platform
import logging
import json
from pathlib import Path

import cv2
import pyvirtualcam
from flask import Flask, jsonify, request

# ==========================
# Paths & logging
# ==========================
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "facecam.log"
CONFIG_FILE = BASE_DIR / "facecam_config.json"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("facecam")

# ==========================
# Global config (shared state)
# ==========================
config_lock = threading.Lock()
config = {
    "camera_index": None,           # int or None
    "orientation": "none",          # "none", "cw", "ccw"
    "detection_every_n_frames": 10, # defaults tuned for less jitter
    "smoothing_alpha": 0.02,
    "margin_factor": 2.8,
}

OUT_W, OUT_H = 640, 640
FPS = 30

app = Flask(__name__)

# ==========================
# Config persistence
# ==========================
def load_persisted_config():
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Failed to read config file %s: %s", CONFIG_FILE, e)
        return

    with config_lock:
        for k, v in data.items():
            if k in config:
                config[k] = v

        # Safety: on Linux, never persist camera_index==0 as input
        if platform.system() == "Linux" and config.get("camera_index") == 0:
            log.info("Resetting persisted camera_index=0 on Linux (loopback).")
            config["camera_index"] = None

    log.info("Loaded persisted config from %s: %s", CONFIG_FILE, data)


def persist_config():
    with config_lock:
        data = dict(config)
    try:
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log.debug("Persisted config to %s: %s", CONFIG_FILE, data)
    except Exception as e:
        log.warning("Failed to write config file %s: %s", CONFIG_FILE, e)


def get_config():
    with config_lock:
        return dict(config)


def update_config(changes: dict):
    with config_lock:
        for k, v in changes.items():
            if k in config:
                config[k] = v
    log.info("Config updated: %s", changes)
    persist_config()


# Load config once at startup
load_persisted_config()

# ==========================
# Camera probing
# ==========================
def list_cameras(max_index=10):
    """Probe camera indices and return those that work as *inputs*.

    On Linux we skip index 0 because it's our v4l2loopback virtual cam (FaceCam).
    We ALWAYS include the currently selected camera_index (if set), even if the
    device is already in use by our own camera_loop.
    """
    cfg = get_config()
    current_idx = cfg.get("camera_index")

    cams = []
    start = 0
    if platform.system() == "Linux":
        start = 1  # /dev/video0 is FaceCam output; don't use as input

    log.debug("Probing cameras %d..%d (current_idx=%s)", start, max_index - 1, current_idx)

    for i in range(start, max_index):
        # If this is the camera our own loop is already using, assume it's valid.
        if current_idx is not None and i == current_idx:
            if i not in cams:
                cams.append(i)
                log.debug("Camera index %d assumed usable (current capture)", i)
            continue

        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                cams.append(i)
                log.debug("Camera index %d is usable", i)
            else:
                log.debug("Camera index %d opened but failed to read frame", i)
        cap.release()

    # Safety: if current_idx is set but wasn't added above for some reason, add it.
    if current_idx is not None and current_idx not in cams:
        cams.append(current_idx)
        log.debug("Camera index %d added from config even though probing failed", current_idx)

    log.info("Detected cameras: %s", cams)
    return cams

# ==========================
# Flask API + UI
# ==========================
INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>FaceCam Controls</title>
  <style>
    body {
      font-family: system-ui, sans-serif;
      background: #111;
      color: #eee;
      padding: 1.5rem;
      max-width: 720px;
      margin: 0 auto;
    }
    h1 {
      font-size: 1.5rem;
      margin-bottom: 1rem;
    }
    h2 {
      font-size: 1.2rem;
      margin-top: 1.5rem;
      margin-bottom: 0.5rem;
    }
    .section {
      margin-bottom: 1.5rem;
      padding: 1rem;
      border-radius: 10px;
      background: #1d1d1d;
    }
    label {
      display: flex;
      justify-content: space-between;
      margin-bottom: 0.25rem;
      font-size: 0.95rem;
    }
    select, button {
      padding: 0.4rem 0.6rem;
      border-radius: 6px;
      border: none;
      margin-right: 0.5rem;
    }
    button {
      cursor: pointer;
    }
    input[type="range"] {
      width: 100%;
    }
    .value {
      margin-left: 0.5rem;
      font-weight: bold;
    }
    .note {
      font-size: 0.8rem;
      color: #aaa;
      margin-top: 0.25rem;
    }
    .orientation-buttons button {
      margin-right: 0.5rem;
    }
    .orientation-buttons button.active {
      background: #3a7bfd;
      color: white;
    }
  </style>
</head>
<body>
  <h1>FaceCam Controls</h1>

  <div class="section">
    <h2>1. Camera</h2>
    <div>
      <select id="camera-select"></select>
      <button id="refresh-cams">Refresh</button>
    </div>
    <div class="note">Select the physical camera to track and crop.</div>
  </div>

  <div class="section">
    <h2>2. Orientation</h2>
    <div class="orientation-buttons">
      <button data-orient="none">No rotation</button>
      <button data-orient="cw">90° clockwise</button>
      <button data-orient="ccw">90° counter-clockwise</button>
    </div>
    <div class="note">Match this to how your camera/phone is physically oriented.</div>
  </div>

  <div class="section">
    <h2>3. Face Tracking</h2>

    <div class="slider-group">
      <label>
        Detection every N frames
        <span class="value" id="det-label"></span>
      </label>
      <input type="range" id="det-slider" min="1" max="30" step="1" />
      <div class="note">Higher = less frequent detection (less CPU, slower reaction).</div>
      <br>
    </div>

    <div class="slider-group">
      <label>
        Smoothing alpha
        <span class="value" id="smooth-label"></span>
      </label>
      <input type="range" id="smooth-slider" min="0.01" max="0.4" step="0.01" />
      <div class="note">Lower = smoother (less jitter), but more lag.</div>
      <br>
    </div>

    <div class="slider-group">
      <label>
        Margin factor
        <span class="value" id="margin-label"></span>
      </label>
      <input type="range" id="margin-slider" min="1.5" max="3.5" step="0.1" />
      <div class="note">Higher = looser framing, moves less when you move.</div>
    </div>
  </div>

  <script>
    async function fetchJSON(url, opts) {
      const res = await fetch(url, opts);
      if (!res.ok) {
        throw new Error("HTTP " + res.status);
      }
      return await res.json();
    }

    async function loadCameras() {
      const data = await fetchJSON('/api/cameras');
      const select = document.getElementById('camera-select');
      select.innerHTML = '';

      if (!Array.isArray(data.cameras) || data.cameras.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'No cameras detected';
        opt.disabled = true;
        opt.selected = true;
        select.appendChild(opt);
        return data;
      }

      data.cameras.forEach(cam => {
        const opt = document.createElement('option');
        opt.value = cam.index;
        opt.textContent = cam.label;
        select.appendChild(opt);
      });
      return data;
    }

    async function loadConfig() {
      return await fetchJSON('/api/config');
    }

    function setOrientationButtons(current) {
      document.querySelectorAll('.orientation-buttons button').forEach(btn => {
        if (btn.dataset.orient === current) {
          btn.classList.add('active');
        } else {
          btn.classList.remove('active');
        }
      });
    }

    async function initUI() {
      try {
        const cams = await loadCameras();
        const cfg = await loadConfig();

        const select = document.getElementById('camera-select');

        // Auto-pick a camera when none is set, for both Linux & Windows.
        if (Array.isArray(cams.cameras) && cams.cameras.length > 0) {
          if (cfg.camera_index !== null && cfg.camera_index !== undefined) {
            const match = cams.cameras.find(c => c.index === cfg.camera_index);
            if (match) {
              select.value = String(cfg.camera_index);
            } else {
              // Saved camera not found -> fall back to first camera and POST it
              const firstIndex = cams.cameras[0].index;
              select.value = String(firstIndex);
              await fetchJSON('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ camera_index: firstIndex })
              });
            }
          } else {
            // No camera selected yet: pick the first one and POST it
            const firstIndex = cams.cameras[0].index;
            select.value = String(firstIndex);
            await fetchJSON('/api/config', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ camera_index: firstIndex })
            });
          }
        }

        // Camera dropdown change handler
        select.addEventListener('change', () => {
          const val = select.value;
          if (val === '') return;
          fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ camera_index: Number(val) })
          }).catch(console.error);
        });

        // Refresh button
        document.getElementById('refresh-cams').addEventListener('click', async () => {
          const cams2 = await loadCameras();
          const cfg2 = await loadConfig();
          const sel = document.getElementById('camera-select');

          if (Array.isArray(cams2.cameras) && cams2.cameras.length > 0 && cfg2.camera_index !== null && cfg2.camera_index !== undefined) {
            const match2 = cams2.cameras.find(c => c.index === cfg2.camera_index);
            if (match2) {
              sel.value = String(cfg2.camera_index);
            }
          }
        });

        // Orientation buttons
        setOrientationButtons(cfg.orientation || 'none');
        document.querySelectorAll('.orientation-buttons button').forEach(btn => {
          btn.addEventListener('click', () => {
            const orient = btn.dataset.orient;
            setOrientationButtons(orient);
            fetchJSON('/api/config', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ orientation: orient })
            }).catch(console.error);
          });
        });

        // Sliders
        const detSlider = document.getElementById('det-slider');
        const smoothSlider = document.getElementById('smooth-slider');
        const marginSlider = document.getElementById('margin-slider');

        const detLabel = document.getElementById('det-label');
        const smoothLabel = document.getElementById('smooth-label');
        const marginLabel = document.getElementById('margin-label');

        detSlider.value = cfg.detection_every_n_frames || 10;
        smoothSlider.value = cfg.smoothing_alpha || 0.02;
        marginSlider.value = cfg.margin_factor || 2.8;

        detLabel.textContent = detSlider.value;
        smoothLabel.textContent = Number(smoothSlider.value).toFixed(2);
        marginLabel.textContent = Number(marginSlider.value).toFixed(2);

        detSlider.addEventListener('input', () => {
          detLabel.textContent = detSlider.value;
          fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ detection_every_n_frames: Number(detSlider.value) })
          }).catch(console.error);
        });

        smoothSlider.addEventListener('input', () => {
          smoothLabel.textContent = Number(smoothSlider.value).toFixed(2);
          fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ smoothing_alpha: Number(smoothSlider.value) })
          }).catch(console.error);
        });

        marginSlider.addEventListener('input', () => {
          marginLabel.textContent = Number(marginSlider.value).toFixed(2);
          fetchJSON('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ margin_factor: Number(marginSlider.value) })
          }).catch(console.error);
        });
      } catch (err) {
        console.error('initUI failed:', err);
      }
    }

    initUI().catch(err => console.error(err));
  </script>
</body>
</html>
"""

@app.route("/")
def index():
    log.debug("HTTP GET /")
    return INDEX_HTML

@app.route("/api/cameras")
def api_cameras():
    log.debug("HTTP GET /api/cameras")
    cams = list_cameras()
    cfg = get_config()
    current_idx = cfg.get("camera_index")
    return jsonify({
        "cameras": [
            {
                "index": i,
                "label": f"Camera {i}" + (" (current)" if i == current_idx else "")
            }
            for i in cams
        ]
    })

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        log.debug("HTTP GET /api/config")
        return jsonify(get_config())
    log.debug("HTTP POST /api/config")
    data = request.get_json(force=True, silent=True) or {}
    log.debug("Config POST payload: %s", data)

    changes = {}
    if "camera_index" in data:
        val = data["camera_index"]
        if isinstance(val, int):
            changes["camera_index"] = val
    if "orientation" in data:
        if data["orientation"] in ("none", "cw", "ccw"):
            changes["orientation"] = data["orientation"]
    if "detection_every_n_frames" in data:
        try:
            n = int(data["detection_every_n_frames"])
            if n < 1:
                n = 1
            changes["detection_every_n_frames"] = n
        except (TypeError, ValueError):
            log.warning("Invalid detection_every_n_frames: %s", data["detection_every_n_frames"])
    if "smoothing_alpha" in data:
        try:
            a = float(data["smoothing_alpha"])
            if a <= 0:
                a = 0.01
            changes["smoothing_alpha"] = a
        except (TypeError, ValueError):
            log.warning("Invalid smoothing_alpha: %s", data["smoothing_alpha"])
    if "margin_factor" in data:
        try:
            m = float(data["margin_factor"])
            if m < 1.0:
                m = 1.0
            changes["margin_factor"] = m
        except (TypeError, ValueError):
            log.warning("Invalid margin_factor: %s", data["margin_factor"])

    if changes:
        update_config(changes)

    return jsonify(get_config())

# ==========================
# Video / face tracking loop
# ==========================
def apply_orientation(frame, orientation):
    if orientation == "cw":
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif orientation == "ccw":
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame

def camera_loop():
    log.info("Starting camera_loop")
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if face_cascade.empty():
        log.error("Failed to load Haar cascade for face detection")

    smooth_cx = smooth_cy = smooth_size = None
    frame_idx = 0
    current_cam_index = None
    cap = None

    # On Linux, explicitly use /dev/video0 (FaceCam loopback).
    # On Windows/macOS, let pyvirtualcam choose the appropriate backend (OBS, etc.).
    if platform.system() == "Linux":
        vcam_device = "/dev/video0"
    else:
        vcam_device = None

    log.info("Initializing virtual camera, device=%s", vcam_device)

    try:
        with pyvirtualcam.Camera(
            width=OUT_W,
            height=OUT_H,
            fps=FPS,
            device=vcam_device,
            print_fps=True,
        ) as vcam:
            log.info("Virtual camera opened: %s", vcam.device)
            log.info("Open http://127.0.0.1:5000 to configure.")
            log.info("Select this virtual camera in Zoom/Meet/etc.")

            while True:
                cfg = get_config()

                if cfg["camera_index"] != current_cam_index:
                    if cap is not None:
                        log.info("Releasing previous capture device index %s", current_cam_index)
                        cap.release()
                        cap = None
                    current_cam_index = cfg["camera_index"]
                    smooth_cx = smooth_cy = smooth_size = None
                    frame_idx = 0

                    if current_cam_index is None:
                        log.debug("No camera_index selected yet, sleeping...")
                        time.sleep(0.1)
                        continue

                    log.info("Opening capture device index %s", current_cam_index)
                    cap = cv2.VideoCapture(current_cam_index)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                    cap.set(cv2.CAP_PROP_FPS, FPS)

                    if not cap.isOpened():
                        log.error("Failed to open capture device index %s", current_cam_index)
                        cap = None
                        time.sleep(1.0)
                        continue

                if cap is None:
                    time.sleep(0.1)
                    continue

                ret, frame = cap.read()
                if not ret:
                    log.warning("Failed to read frame from camera index %s", current_cam_index)
                    time.sleep(0.05)
                    continue

                frame_idx += 1

                frame = apply_orientation(frame, cfg["orientation"])

                det_n = max(1, int(cfg["detection_every_n_frames"]))
                alpha = float(cfg["smoothing_alpha"])
                margin = float(cfg["margin_factor"])

                if frame_idx % det_n == 0:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.3,
                        minNeighbors=5,
                        minSize=(60, 60),
                    )
                    log.debug("Frame %d: detected %d face(s)", frame_idx, len(faces))
                    if len(faces) > 0:
                        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                        cx = x + w // 2
                        cy = y + h // 2
                        size = max(w, h)

                        if smooth_cx is None:
                            smooth_cx, smooth_cy, smooth_size = cx, cy, size
                            log.debug("Initialized smooth face: cx=%d cy=%d size=%d", cx, cy, size)
                        else:
                            smooth_cx = (1 - alpha) * smooth_cx + alpha * cx
                            smooth_cy = (1 - alpha) * smooth_cy + alpha * cy
                            smooth_size = (1 - alpha) * smooth_size + alpha * size
                            log.debug(
                                "Updated smooth face: cx=%.1f cy=%.1f size=%.1f",
                                smooth_cx, smooth_cy, smooth_size
                            )

                h_f, w_f, _ = frame.shape

                if smooth_cx is None or smooth_cy is None or smooth_size is None:
                    # No face yet: center square crop
                    size = min(h_f, w_f)
                    x0 = (w_f - size) // 2
                    y0 = (h_f - size) // 2
                    crop = frame[y0:y0 + size, x0:x0 + size]
                else:
                    # Always keep a square crop to avoid aspect-ratio distortion
                    max_square = min(h_f, w_f)
                    desired = int(smooth_size * margin)
                    # Clamp size so it fits in frame and isn't absurdly tiny
                    size = max(50, min(desired, max_square))

                    cx = int(round(smooth_cx))
                    cy = int(round(smooth_cy))

                    # Initial top-left
                    x1 = cx - size // 2
                    y1 = cy - size // 2

                    # Clamp so the square fits fully inside the frame
                    if x1 < 0:
                        x1 = 0
                    if y1 < 0:
                        y1 = 0
                    if x1 + size > w_f:
                        x1 = w_f - size
                    if y1 + size > h_f:
                        y1 = h_f - size

                    # Final bounds
                    x2 = x1 + size
                    y2 = y1 + size

                    crop = frame[y1:y2, x1:x2]
                    if crop.size == 0 or crop.shape[0] != crop.shape[1]:
                        log.warning(
                            "Non-square or empty crop detected (%dx%d), falling back to center crop",
                            crop.shape[1] if crop.size else -1,
                            crop.shape[0] if crop.size else -1,
                        )
                        size = min(h_f, w_f)
                        x0 = (w_f - size) // 2
                        y0 = (h_f - size) // 2
                        crop = frame[y0:y0 + size, x0:x0 + size]

                crop = cv2.resize(crop, (OUT_W, OUT_H))
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                vcam.send(rgb)
                vcam.sleep_until_next_frame()
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt: exiting camera_loop")
    except Exception:
        log.exception("Unhandled exception in camera_loop")
    finally:
        if cap is not None:
            log.info("Releasing capture device on exit")
            cap.release()
        log.info("camera_loop finished")

def run_flask():
    log.info("Starting Flask server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

def main():
    log.info("FaceCam starting up (platform=%s)", platform.system())
    t = threading.Thread(target=run_flask, daemon=True, name="FlaskThread")
    t.start()
    camera_loop()

if __name__ == "__main__":
    main()
