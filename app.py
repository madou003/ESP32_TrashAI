from flask import Flask, render_template, jsonify, Response, request
import serial, time
import cv2
import csv, os, json
from datetime import datetime

import ai_bridge as core  # your existing AI/serial/vision code


app = Flask(__name__, static_folder="static")  # templates/ used by default

ser = None
model = None
class_names = None

# ---- Camera globals for live stream ----
camera = None        # cv2.VideoCapture
last_frame = None    # last frame from the stream

# ---- Paths for logs and settings ----
LOG_PATH = "detection_log.csv"
SETTINGS_PATH = "settings.json"


# ---------- Helpers: settings & logging ----------

def default_settings():
    return {
        "organic": 20,
        "plastic": 50,
        "metal": 30,
        "paper": 40,
    }


def load_settings():
    if not os.path.exists(SETTINGS_PATH):
        return default_settings()
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    base = default_settings()
    for k, v in data.items():
        try:
            base[k] = int(v)
        except (ValueError, TypeError):
            pass
    return base


def save_settings(cfg):
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def log_detection(label, raw_label, confidence):
    """
    Append a detection row into CSV log.
    """
    exists = os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not exists:
            writer.writerow(["timestamp", "label", "raw_label", "confidence"])
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            str(label),
            str(raw_label),
            float(confidence),
        ])


def load_detection_counts():
    """
    Read detection_log.csv and return (total, per_label_dict).
    Labels are uppercased for consistency.
    """
    if not os.path.exists(LOG_PATH):
        return 0, {}

    per = {}
    total = 0
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            lab = (row.get("label") or "UNKNOWN").upper()
            total += 1
            per[lab] = per.get(lab, 0) + 1
    return total, per


# ---------- Camera helpers ----------

def get_camera():
    """Return global VideoCapture, open it if needed."""
    global camera
    if camera is None:
        cam_index = getattr(core, "CAM_INDEX", 0)
        print(f"[CAM] Opening camera index {cam_index}")
        camera = cv2.VideoCapture(cam_index)
        if not camera.isOpened():
            print(f"[CAM] ERROR: cannot open camera index {cam_index}")
            camera = None
    return camera


def gen_frames():
    """
    Generator that yields JPEG frames for MJPEG streaming.
    Also updates last_frame so /api/scan can use the current frame.
    """
    global last_frame
    cam = get_camera()
    while True:
        if cam is None:
            break

        success, frame = cam.read()
        if not success:
            break

        last_frame = frame  # store for snapshot detection

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue

        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )


# ---------- Core init (serial + model) ----------

def init_once():
    """Init serial + model + labels only once."""
    global ser, model, class_names
    if ser is not None:
        return

    # ---- Serial ----
    port = getattr(core, "SERIAL_PORT", None) or core.pick_port()
    if not port:
        raise RuntimeError("No serial port found. Set SERIAL_PORT in ai_bridge.py")

    baud = getattr(core, "BAUD", 115200)
    print(f"[INIT] Opening serial on {port} at {baud}")
    ser = serial.Serial(port, baud, timeout=0.1)
    time.sleep(2)

    # ---- Model + labels ----
    print("[INIT] Loading model + labels…")
    # If your ai_bridge already has load_model, use it; otherwise fallback
    if hasattr(core, "load_model"):
        model_fn = core.load_model
    else:
        from tf_keras.models import load_model
        model_fn = load_model

    model_path = getattr(core, "MODEL_PATH", "trash.h5")
    labels_path = getattr(core, "LABELS_PATH", "labels.txt")

    model = model_fn(model_path, compile=False)
    class_names = core.load_labels(labels_path)

    print("[INIT] Ready")
    print("  MODEL_PATH :", model_path)
    print("  LABELS_PATH:", labels_path)
    print("  CLASSES    :", class_names)
    print("  ALLOWED    :", getattr(core, "ALLOWED_CLASSES",
                                     {"PLASTIC", "PAPER", "METAL"}))


# ---------- Page routes ----------

@app.route("/")
def home():
    init_once()
    return render_template("index.html")


@app.route("/data_analytics.html")
def data_analytics():
    init_once()
    return render_template("data_analytics.html")


@app.route("/ai_detection.html")
def ai_detection():
    init_once()
    return render_template("ai_detection.html")


@app.route("/settings.html")
def settings():
    init_once()
    return render_template("settings.html")


@app.route("/login.html")
def login():
    init_once()
    return render_template("login.html")


# ---------- Video stream route ----------

@app.route("/video_feed")
def video_feed():
    """
    Live video stream endpoint.
    Use <img src="{{ url_for('video_feed') }}"> in ai_detection.html.
    """
    return Response(
        gen_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


# ---------- API: global status ----------

@app.route("/api/status")
def api_status():
    init_once()
    return jsonify({"status": "ok"})


# ---------- API: AI scan ----------

@app.post("/api/scan")
def api_scan():
    """
    1) Take the current frame from live stream
    2) Run prediction
    3) Send label to ESP32 (PLASTIC/PAPER/METAL/UNKNOWN)
    4) Log detection for analytics
    """
    init_once()
    global ser, model, class_names, last_frame

    cam = get_camera()

    # 1. Get frame from live stream
    frame = last_frame
    if frame is None:
        # If stream not started yet, grab one frame manually
        if cam is None:
            return jsonify({"error": "Camera not available"}), 500
        success, frame = cam.read()
        if not success or frame is None:
            return jsonify({"error": "Cannot read from camera"}), 500

    img = frame  # OpenCV BGR image

    # 2. Predict top class
    topk = getattr(core, "TOPK", 3)
    top, img224, probs = core.predict_top(model, class_names, img, topk)
    best_raw, best_prob, _ = top[0]
    best_mapped = core.apply_alias(best_raw)

    allowed = getattr(core, "ALLOWED_CLASSES", {"PLASTIC", "PAPER", "METAL"})
    result = best_mapped if best_mapped in allowed else "UNKNOWN"

    # 3. Optional debug image saving
    if getattr(core, "SAVE_DEBUG", False):
        full_path, crop_path = core.save_debug_images(img, img224)
        print(f"[DEBUG] Saved: {full_path}, {crop_path}")

    # 4. Send to ESP32
    msg = result + "\n"
    print(f"[SCAN] Sending -> {msg.strip()}  (raw={best_raw}, conf={best_prob:.2%})")
    ser.write(msg.encode("utf-8"))

    # 5. Log detection for analytics
    log_detection(result, best_raw, best_prob)

    return jsonify({
        "label": result,
        "raw_label": best_raw,
        "confidence": float(best_prob)
    })


# ---------- API: manual label send ----------

@app.post("/api/send_label/<label>")
def api_send_label(label):
    """
    Manual control from buttons: PLASTIC/PAPER/METAL/UNKNOWN.
    """
    init_once()
    global ser

    allowed = getattr(core, "ALLOWED_CLASSES", {"PLASTIC", "PAPER", "METAL"})
    allowed = allowed | {"UNKNOWN"}

    label_up = label.upper()
    if label_up not in allowed:
        return jsonify({"error": f"Invalid label '{label}'. Use {sorted(list(allowed))}."}), 400

    msg = label_up + "\n"
    ser.write(msg.encode("utf-8"))
    print(f"[MANUAL] Sent -> {msg.strip()}")
    return jsonify({"sent": label_up})


# ---------- API: settings (thresholds) ----------

@app.get("/api/settings")
def api_get_settings():
    """
    Return current material thresholds.
    """
    cfg = load_settings()
    return jsonify(cfg)


@app.post("/api/settings")
def api_save_settings():
    """
    Save material thresholds from frontend sliders.
    Body JSON: { "organic": 10, "plastic": 60, "metal": 30, "paper": 20 }
    """
    cfg = load_settings()
    payload = request.get_json(silent=True) or {}

    for key in ["organic", "plastic", "metal", "paper"]:
        if key in payload:
            try:
                cfg[key] = int(payload[key])
            except (ValueError, TypeError):
                pass

    save_settings(cfg)
    print("[SETTINGS UPDATED]", cfg)
    return jsonify({"status": "ok", "data": cfg})


# ---------- API: detection stats & bin status ----------

@app.get("/api/detection_stats")
def api_detection_stats():
    """
    Return stats from detection_log.csv
    {
      "total": 12,
      "per_label": {"PLASTIC": 5, "PAPER": 3, "METAL": 4, "UNKNOWN": 0}
    }
    """
    total, per = load_detection_counts()
    return jsonify({"total": total, "per_label": per})


@app.get("/api/bin_status")
def api_bin_status():
    """
    Compute bin fill percentage per material based on detection counts
    and thresholds. This is a software estimation, not physical sensor.
    """
    cfg = load_settings()
    _total, per = load_detection_counts()

    result = {}
    # our AI labels are PLASTIC, METAL, PAPER. ORGANIC will be 0 unless you add that label.
    mapping = {
        "organic": "ORGANIC",
        "plastic": "PLASTIC",
        "metal": "METAL",
        "paper": "PAPER",
    }

    for key, label_name in mapping.items():
        count = per.get(label_name, 0)
        threshold_items = max(1, cfg.get(key, 1))
        percent = int(min(100, round(100.0 * count / threshold_items)))
        result[key] = percent

    return jsonify(result)


if __name__ == "__main__":
    # Run backend
    app.run(host="0.0.0.0", port=5000, debug=True)
