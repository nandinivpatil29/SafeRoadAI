from flask import Flask, render_template, request, jsonify, Response
from ultralytics import YOLO
import cv2, os, threading, time, sqlite3, json, smtplib
from email.message import EmailMessage
from datetime import datetime
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "saferoad.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
ALLOWED_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "webm"}

# Vehicle classes in COCO-trained YOLO models: bicycle, car, motorcycle, bus, truck.
VEHICLE_CLASS_IDS = {1, 2, 3, 5, 7}
MODEL_NAME = os.environ.get("SAFEROAD_MODEL", "yolo11n.pt")

state_lock = threading.Lock()
state = {
    "running": False,
    "source": "none",
    "message": "Ready. Choose a recorded video or start the server webcam.",
    "vehicles": 0,
    "fps": 0,
    "candidate": False,
    "last_candidate_at": None,
    "frame": None,
    "stop_requested": False,
    "thread": None,
    "cap": None,
}
model = None
model_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'Unverified',
            notes TEXT,
            snapshot_path TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS app_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL
        )
        """)

def log_event(event_type, message):
    with get_db() as conn:
        conn.execute("INSERT INTO app_events(created_at,event_type,message) VALUES(?,?,?)",
                     (datetime.now().isoformat(timespec="seconds"), event_type, message))

def add_incident(source, event_type, confidence=None, notes="", snapshot=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO incidents(created_at,source,event_type,confidence,status,notes,snapshot_path) VALUES(?,?,?,?,?,?,?)",
            (datetime.now().isoformat(timespec="seconds"), source, event_type, confidence, "Unverified", notes, snapshot)
        )
        incident_id = cur.lastrowid
    log_event("incident", f"Incident #{incident_id}: {event_type} (unverified)")
    return incident_id

def get_model():
    global model
    with model_lock:
        if model is None:
            # On first run, Ultralytics downloads the official pretrained weights.
            model = YOLO(MODEL_NAME)
        return model

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def box_iou(a, b):
    x1 = max(a[0], b[0]); y1 = max(a[1], b[1])
    x2 = min(a[2], b[2]); y2 = min(a[3], b[3])
    inter = max(0, x2-x1) * max(0, y2-y1)
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    denom = area_a + area_b - inter
    return inter / denom if denom else 0.0

def process_video(source_kind, source_value, loop_video=False):
    global state
    cap = None
    last_time = time.time()
    frame_count = 0
    # Consecutive overlap observations are a weak visual cue only, not proof of a crash.
    overlap_streak = 0
    candidate_cooldown_until = 0
    try:
        if source_kind == "camera":
            cap = cv2.VideoCapture(0)
        else:
            cap = cv2.VideoCapture(source_value)
        if not cap or not cap.isOpened():
            with state_lock:
                state["message"] = "Could not open the video source. Check camera permission or file format."
                state["running"] = False
            return
        with state_lock:
            state["cap"] = cap
            state["message"] = "Analyzing frames. Vehicle detection is not the same as accident detection."
        yolo = get_model()
        while True:
            with state_lock:
                should_stop = state["stop_requested"]
            if should_stop:
                break
            ok, frame = cap.read()
            if not ok:
                if source_kind == "file" and loop_video:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    overlap_streak = 0
                    continue
                break
            frame_count += 1
            # Run detection on each frame for clarity; on slower laptops, lower inference size.
            results = yolo.predict(frame, conf=0.35, imgsz=640, verbose=False)
            result = results[0]
            boxes = []
            vehicle_count = 0
            if result.boxes is not None:
                for b in result.boxes:
                    cls_id = int(b.cls[0].item())
                    if cls_id not in VEHICLE_CLASS_IDS:
                        continue
                    conf = float(b.conf[0].item())
                    xyxy = [int(v) for v in b.xyxy[0].tolist()]
                    boxes.append((xyxy, conf))
                    vehicle_count += 1
                    x1, y1, x2, y2 = xyxy
                    label = f"{result.names.get(cls_id, 'vehicle')} {conf:.2f}"
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (60, 210, 120), 2)
                    cv2.putText(frame, label, (x1, max(20, y1-8)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 210, 120), 2)

            # Conservative candidate heuristic: repeated high overlap between two vehicle boxes.
            # This is a demo signal only and is intentionally labelled unverified.
            max_overlap = 0.0
            for i in range(len(boxes)):
                for j in range(i+1, len(boxes)):
                    max_overlap = max(max_overlap, box_iou(boxes[i][0], boxes[j][0]))
            if max_overlap > 0.30:
                overlap_streak += 1
            else:
                overlap_streak = max(0, overlap_streak - 1)
            now = time.time()
            if overlap_streak >= 8 and now >= candidate_cooldown_until:
                snapshot_name = f"candidate_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                snapshot_path = os.path.join("uploads", snapshot_name)
                cv2.imwrite(os.path.join(UPLOAD_DIR, snapshot_name), frame)
                add_incident(source_kind, "Possible vehicle overlap — review required", min(0.99, max_overlap),
                             "Heuristic candidate only; overlap can occur without a collision.", snapshot_path)
                candidate_cooldown_until = now + 45
                overlap_streak = 0
                cv2.putText(frame, "POSSIBLE EVENT - REVIEW REQUIRED", (20, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
            fps = 1.0 / max(0.001, now-last_time)
            last_time = now
            cv2.putText(frame, "SafeRoad AI | vehicle detections only; event candidates are unverified",
                        (10, frame.shape[0]-15), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255,255,255), 1)
            ok_jpg, buffer = cv2.imencode(".jpg", frame)
            if ok_jpg:
                with state_lock:
                    state["frame"] = buffer.tobytes()
                    state["vehicles"] = vehicle_count
                    state["fps"] = round(fps, 1)
                    state["candidate"] = overlap_streak > 0
                    state["last_candidate_at"] = datetime.now().isoformat(timespec="seconds") if overlap_streak > 0 else state["last_candidate_at"]
            time.sleep(0.01)
        with state_lock:
            state["message"] = "Video finished." if source_kind == "file" else "Camera stopped."
    except Exception as exc:
        with state_lock:
            state["message"] = f"Processing error: {exc}"
        log_event("error", str(exc)[:500])
    finally:
        if cap is not None:
            cap.release()
        with state_lock:
            state["cap"] = None
            state["running"] = False
            state["source"] = "none"
            state["stop_requested"] = False

def start_source(kind, value=None, loop_video=False):
    with state_lock:
        if state["running"]:
            return False, "A source is already running. Stop it before starting another."
        state["running"] = True
        state["source"] = kind
        state["stop_requested"] = False
        state["message"] = "Starting AI model; first startup may download model weights."
        state["vehicles"] = 0
        state["candidate"] = False
        thread = threading.Thread(target=process_video, args=(kind, value, loop_video), daemon=True)
        state["thread"] = thread
        thread.start()
    return True, "Started"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def api_status():
    with state_lock:
        return jsonify({
            "running": state["running"], "source": state["source"], "message": state["message"],
            "vehicles": state["vehicles"], "fps": state["fps"], "candidate": state["candidate"]
        })

@app.route("/api/start-camera", methods=["POST"])
def start_camera():
    ok, msg = start_source("camera")
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 409)

@app.route("/api/upload-video", methods=["POST"])
def upload_video():
    if "video" not in request.files:
        return jsonify({"ok": False, "message": "Choose a video file first."}), 400
    f = request.files["video"]
    if not f.filename or not allowed_file(f.filename):
        return jsonify({"ok": False, "message": "Supported formats: MP4, AVI, MOV, MKV, WEBM."}), 400
    filename = secure_filename(f"{int(time.time())}_{f.filename}")
    path = os.path.join(UPLOAD_DIR, filename)
    f.save(path)
    loop_video = request.form.get("loop") == "true"
    ok, msg = start_source("file", path, loop_video)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 409)

@app.route("/api/stop", methods=["POST"])
def stop():
    with state_lock:
        state["stop_requested"] = True
        state["message"] = "Stopping source..."
    return jsonify({"ok": True, "message": "Stop requested."})

@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            with state_lock:
                frame = state["frame"]
                running = state["running"]
            if frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            elif not running:
                time.sleep(0.2)
            else:
                time.sleep(0.05)
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

@app.route("/api/incidents")
def incidents():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/incidents/<int:incident_id>/status", methods=["POST"])
def update_incident(incident_id):
    status = (request.json or {}).get("status", "")
    if status not in {"Unverified", "Reviewed", "False alarm", "Confirmed by human"}:
        return jsonify({"ok": False, "message": "Invalid status."}), 400
    with get_db() as conn:
        cur = conn.execute("UPDATE incidents SET status=? WHERE id=?", (status, incident_id))
        if cur.rowcount == 0:
            return jsonify({"ok": False, "message": "Incident not found."}), 404
    log_event("review", f"Incident #{incident_id} marked {status}")
    return jsonify({"ok": True})

@app.route("/api/test-incident", methods=["POST"])
def test_incident():
    incident_id = add_incident("manual test", "TEST ALERT — not a real accident", 1.0,
                                "Manually generated demonstration event. No emergency services contacted.")
    return jsonify({"ok": True, "id": incident_id, "message": "Demo incident added. No external emergency contact was made."})

@app.route("/api/test-notification", methods=["POST"])
def test_notification():
    # Safe default: no real message is sent unless SMTP environment variables are configured.
    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    recipient = os.environ.get("ALERT_TO")
    sender = os.environ.get("ALERT_FROM", user or "")
    if not all([host, user, password, recipient, sender]):
        log_event("notification", "Test notification requested; SMTP not configured, so no email was sent.")
        return jsonify({"ok": False, "message": "SMTP is not configured. No email was sent. See README to configure test email."}), 400
    msg = EmailMessage()
    msg["Subject"] = "[SafeRoad AI] Test notification"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content("This is a SafeRoad AI test notification. It is not an accident alert.")
    try:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)
        log_event("notification", f"Test email sent to {recipient}")
        return jsonify({"ok": True, "message": f"Test email sent to {recipient}."})
    except Exception as exc:
        log_event("notification_error", str(exc)[:500])
        return jsonify({"ok": False, "message": f"Email failed: {exc}"}), 500

@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, filename)

@app.route("/api/events")
def events():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM app_events ORDER BY id DESC LIMIT 30").fetchall()
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    init_db()
    print("SafeRoad AI starting at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
