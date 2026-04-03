# bridge_ai.py  — robust ESP32 <-> Webcam <-> Keras bridge

import os, time, hashlib, cv2, numpy as np
import serial, serial.tools.list_ports
from PIL import Image, ImageOps
from tf_keras.models import load_model

# ======= USER CONFIG =======
SERIAL_PORT = "COM3"     # set your port explicitly to avoid auto-pick surprises
BAUD        = 115200
CAM_INDEX   = 0          # try 1 if you have multiple cameras
MODEL_PATH  = "trash.h5"
LABELS_PATH = "labels.txt"

CONF_THRESH = 0.60       # retake if below this
TOPK        = 3
SAVE_DEBUG  = True       # save frames used for inference
# Map/merge labels here without editing labels.txt or retraining:
# Example: GLASS should be treated as METAL
LABEL_ALIAS = {
    "GLASS": "METAL",
}
# The only classes we will ever send back to ESP32:
ALLOWED_CLASSES = {"PLASTIC", "PAPER", "METAL"}
# ===========================


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pick_port():
    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        if ("USB" in p.device) or ("COM" in p.device):
            return p.device
    return None


def load_labels(path):
    raw = [l.strip() for l in open(path, "r", encoding="utf-8").readlines() if l.strip()]
    def clean(s):
        # Teachable Machine often uses "0 ClassName"
        return s.split(" ", 1)[1] if (s and s[0].isdigit() and " " in s) else s
    names = [clean(s).upper() for s in raw]
    return names


def apply_alias(label: str) -> str:
    return LABEL_ALIAS.get(label, label)


def preprocess_for_tm(image_bgr):
    """
    OpenCV frame (BGR) -> RGB PIL -> center-crop/resize 224x224 -> float32 [-1,1]
    Returns (x[1,224,224,3], img224_rgb_uint8)
    """
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(image_rgb)
    pil_224 = ImageOps.fit(pil_img, (224, 224), Image.Resampling.LANCZOS).convert("RGB")
    arr = np.asarray(pil_224, dtype=np.float32)
    arr = (arr / 127.5) - 1.0
    x = np.expand_dims(arr, 0)
    return x, np.asarray(pil_224)  # uint8 RGB for saving/visualization


def predict_top(model, class_names, image_bgr, topk=3):
    x, img224 = preprocess_for_tm(image_bgr)
    probs = model.predict(x, verbose=0)[0]
    order = np.argsort(-probs)[:topk]
    top = [(class_names[i], float(probs[i]), i) for i in order]
    return top, img224, probs


def save_debug_images(img_full_bgr, img224_rgb, out_dir="debug_captures"):
    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    full_path   = os.path.join(out_dir, f"{ts}_full.jpg")
    crop_path   = os.path.join(out_dir, f"{ts}_224rgb.jpg")
    cv2.imwrite(full_path, img_full_bgr)                 # BGR
    Image.fromarray(img224_rgb).save(crop_path)          # RGB
    return full_path, crop_path


def capture_from_webcam(cam_index=0):
    cap = cv2.VideoCapture(cam_index)
    if not cap.isOpened():
        raise RuntimeError("Could not open webcam. Try CAM_INDEX=1.")

    print("Press SPACE to capture, ESC to cancel, 's' to switch camera.")
    current_index = cam_index
    frame = None
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        show = frame.copy()
        cv2.putText(show, "SPACE=capture  ESC=cancel  S=switch cam",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255,255,255), 2)
        cv2.imshow("Camera", show)
        k = cv2.waitKey(1) & 0xFF
        if k == 27:  # ESC
            frame = None
            break
        if k == ord('s'):  # switch camera
            current_index = 1 - current_index
            cap.release()
            cap = cv2.VideoCapture(current_index)
            continue
        if k == 32:  # SPACE
            break
    cap.release()
    cv2.destroyAllWindows()
    return frame


def main():
    # --- Serial port ---
    port = SERIAL_PORT or pick_port()
    if not port:
        raise RuntimeError("No serial port found. Set SERIAL_PORT explicitly.")
    print(f"Opening serial: {port}")
    ser = serial.Serial(port, BAUD, timeout=0.1)
    time.sleep(2)

    # --- Model & labels ---
    print("Loading model…")
    model = load_model(MODEL_PATH, compile=False)
    class_names = load_labels(LABELS_PATH)
    print("MODEL SHA256 :", sha256_file(MODEL_PATH))
    print("LABELS SHA256:", sha256_file(LABELS_PATH))
    print("CLASS NAMES (ORDER):", class_names)
    if LABEL_ALIAS:
        print("LABEL_ALIAS mapping:", LABEL_ALIAS)

    print("\nReady. Waiting for 'DETECT' from ESP32…\n")

    try:
        while True:
            line = ser.readline().decode(errors="ignore").strip()
            if not line:
                continue

            # Uncomment to see all ESP32 prints
            # print("ESP32:", line)

            if line == "DETECT":
                while True:
                    img = capture_from_webcam(CAM_INDEX)
                    if img is None:
                        print("Capture cancelled; sending UNKNOWN")
                        ser.write(b"UNKNOWN\n")
                        break

                    top, img224, probs = predict_top(model, class_names, img, TOPK)

                    # print top-k
                    print("Top-k predictions:")
                    for rank, (lbl, p, _) in enumerate(top, 1):
                        print(f"  {rank}. {lbl:<15} {p:.4f}")

                    # best class + alias mapping (e.g., GLASS -> METAL)
                    best_raw, best_prob, best_idx = top[0]
                    best_mapped = apply_alias(best_raw)

                    # Save debug images
                    if SAVE_DEBUG:
                        full_path, crop_path = save_debug_images(img, img224)
                        print(f"Saved: {full_path} and {crop_path}")

                    # low confidence? allow quick retake
                    if best_prob < CONF_THRESH:
                        print(f"Low confidence ({best_prob:.2%}). Retake? [y/N]")
                        ans = input().strip().lower()
                        if ans == "y":
                            continue

                    # whitelist for ESP32
                    result = best_mapped if best_mapped in ALLOWED_CLASSES else "UNKNOWN"
                    print(f"Sending -> {result}  (raw={best_raw}, conf={best_prob:.2%})\n")
                    ser.write((result + "\n").encode("utf-8"))
                    break
    except KeyboardInterrupt:
        print("Exiting…")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
