from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
import serial, time

import ai_bridge as core  # if your file is ai_bridge.py, rename it or update this import

app = FastAPI()

# Globals initialized at startup
ser = None
model = None
class_names = None


class ScanResponse(BaseModel):
    label: str
    confidence: float
    raw_label: str


@app.on_event("startup")
def startup_event():
    """
    Init serial + model + labels once when the server starts.
    """
    global ser, model, class_names

    # ---- Serial ----
    port = core.SERIAL_PORT or core.pick_port()
    if not port:
        raise RuntimeError("No serial port found. Set SERIAL_PORT in bridge_ai.py")

    print(f"[INIT] Opening serial on {port} at {core.BAUD}")
    ser = serial.Serial(port, core.BAUD, timeout=0.1)
    time.sleep(2)

    # ---- Model + labels ----
    print("[INIT] Loading model and labels…")
    from tf_keras.models import load_model  # imported also in bridge_ai, but safe

    model = load_model(core.MODEL_PATH, compile=False)
    class_names = core.load_labels(core.LABELS_PATH)

    print("[INIT] Ready.")
    print("  MODEL_PATH :", core.MODEL_PATH)
    print("  LABELS_PATH:", core.LABELS_PATH)
    print("  CLASS NAMES:", class_names)


@app.get("/status")
def status():
    """
    Quick endpoint to check if server is alive.
    """
    return {"status": "ok", "serial_port": core.SERIAL_PORT, "baud": core.BAUD}


@app.post("/scan", response_model=ScanResponse)
def scan():
    """
    1) Open webcam (with preview window)
    2) You press SPACE -> capture
    3) Run model, map alias, whitelist
    4) Send label to ESP32 over serial
    5) Return JSON with result
    """
    global ser, model, class_names
    if ser is None or model is None or class_names is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    # 1. Capture frame – uses your existing function (SPACE to capture, ESC to cancel)
    img = core.capture_from_webcam(core.CAM_INDEX)
    if img is None:
        raise HTTPException(status_code=400, detail="Capture cancelled")

    # 2. Predict top-k
    top, img224, probs = core.predict_top(model, class_names, img, core.TOPK)
    best_raw, best_prob, _ = top[0]
    best_mapped = core.apply_alias(best_raw)

    # 3. Map to allowed classes
    result = best_mapped if best_mapped in core.ALLOWED_CLASSES else "UNKNOWN"

    # 4. Optionally save debug images (same as your main script)
    if core.SAVE_DEBUG:
        full_path, crop_path = core.save_debug_images(img, img224)
        print(f"[DEBUG] Saved: {full_path} and {crop_path}")

    # 5. Send to ESP32
    msg = result + "\n"
    print(f"[SCAN] Sending to ESP32 -> {msg.strip()} (raw={best_raw}, conf={best_prob:.2%})")
    ser.write(msg.encode("utf-8"))

    # 6. Return JSON for website
    return ScanResponse(label=result, confidence=best_prob, raw_label=best_raw)


@app.post("/send_label/{label}")
def send_label(label: str):
    """
    Manual control: send a label directly to ESP32 from the website.
    Example: POST /send_label/PLASTIC
    """
    global ser
    label_upper = label.upper()
    if label_upper not in (core.ALLOWED_CLASSES | {"UNKNOWN"}):
        raise HTTPException(status_code=400, detail=f"Invalid label '{label}'. Use PLASTIC/PAPER/METAL/UNKNOWN.")
    msg = label_upper + "\n"
    ser.write(msg.encode("utf-8"))
    print(f"[MANUAL] Sent -> {msg.strip()}")
    return {"sent": label_upper}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
