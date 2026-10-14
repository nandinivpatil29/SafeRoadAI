# SafeRoad AI — College Major Project Prototype

A local Flask + OpenCV + Ultralytics YOLO prototype for vehicle detection, recorded-video analysis, a server webcam feed, incident logging, manual review, and an optional test email.

## Safety and model limitations

- The included pretrained YOLO model detects objects such as cars, buses, motorcycles, bicycles, and trucks. **Vehicle detection is not accident detection.**
- This demo uses repeated overlap between detected vehicle bounding boxes as a weak event-candidate heuristic. Overlap can occur because vehicles are close together, boxes are imprecise, or perspective causes overlap. It can miss real collisions and produce false positives.
- Any automatically logged candidate is marked **Unverified** and must be reviewed by a human. The “Create demo incident” button creates a clearly labelled test event.
- This project does not contact emergency services, dispatch responders, or claim safety-critical accuracy. Do not deploy it for real emergency response.
- Test only with videos you are permitted to use. Follow privacy rules when recording people or vehicles.

## Requirements

- Windows 10/11
- Python 3.10 or 3.11 recommended
- VS Code (optional but recommended)
- Internet for the first model-weight download
- A webcam for live-camera mode; recorded-video mode works without one

## Windows setup (VS Code)

1. Extract the ZIP to a folder such as `C:\Projects\SafeRoadAI`.
2. Install Python 3.10 or 3.11 from https://www.python.org/downloads/ and tick **Add Python to PATH** during setup.
3. Open the extracted folder in VS Code.
4. Open **Terminal → New Terminal**.
5. Create a virtual environment:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If `py -3.11` is not available, use `python -m venv .venv`. If PowerShell blocks activation, use Command Prompt terminal and run `.venv\Scripts\activate.bat`, or use `.venv\Scripts\python.exe` directly.

6. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

   On the first run, Ultralytics downloads `yolo11n.pt`. The first launch may take a few minutes and needs internet. If the model download is blocked, download the official `yolo11n.pt` weights from the Ultralytics documentation/release source and place them in the project folder, then retry.

7. Start the app:

   ```powershell
   python app.py
   ```

8. Open Chrome and visit:

   `http://127.0.0.1:5000`

Keep the terminal open while using the website. Press `Ctrl+C` in the terminal to shut down Flask.

## Using the app

### Recorded road video
- Click **Choose road video** and select MP4, AVI, MOV, MKV, or WEBM.
- Optionally enable **Loop video** to repeat the clip.
- Wait for the stream to appear. The app overlays detected vehicles.
- Repeated high overlap may create an unverified candidate record. This is only a heuristic, not proof of a crash.

### Live webcam
- Click **Start webcam**. The webcam is attached to the computer running Flask, not necessarily the browser's computer.
- If Windows asks for camera permission, allow access to desktop apps.
- Close other applications that may be using the webcam.
- To use a phone camera, you would need a separate stream/ingestion implementation; this version does not automatically connect to a phone camera.

### Incident history and test alert
- Use **Create demo incident** to demonstrate the workflow. It does not represent a real crash and does not send an email.
- In Incident History, select Reviewed, False alarm, or Confirmed by human after a manual review.
- The local SQLite database `saferoad.db` is created automatically.

### Test email (optional)
The app sends a test-only email if all required environment variables are configured. No real email is sent by default.

In PowerShell, set the values in the same terminal before starting `python app.py`:

```powershell
$env:SMTP_HOST="smtp.gmail.com"
$env:SMTP_PORT="587"
$env:SMTP_USER="your-sender@gmail.com"
$env:SMTP_PASSWORD="your-provider-app-password"
$env:ALERT_FROM="your-sender@gmail.com"
$env:ALERT_TO="your-test-recipient@example.com"
python app.py
```

For Gmail, use an App Password where eligible; do not use your normal account password. Do not commit credentials to GitHub or share them with teammates. The test email explicitly says it is not an accident alert.

## Folder structure

```text
SafeRoadAI/
├── app.py
├── requirements.txt
├── README.md
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── app.js
└── uploads/
    └── .gitkeep
```

Runtime files (`saferoad.db`, uploaded clips and snapshots, and model weights) are generated locally and are ignored by Git.

## Architecture

1. Flask serves the dashboard and JSON API.
2. OpenCV reads the server webcam or uploaded video.
3. YOLO pretrained weights detect vehicle objects per frame.
4. A conservative repeated-overlap heuristic can create an **unverified event candidate**.
5. SQLite stores incidents and event logs.
6. The dashboard polls status and incident history.
7. Optional SMTP sends a clearly labelled test email only.

## Dataset and future improvement

For research, investigate:
- UCF-Crime (includes an accident category among surveillance anomaly classes): https://www.crcv.ucf.edu/projects/real-world/
- DoTA — Detection of Traffic Anomaly: https://github.com/MoonBlvd/Detection-of-Traffic-Anomaly
- AI City Challenge: https://www.aicitychallenge.org/

Review the access terms, annotations, and licences before downloading, training, or redistributing datasets.

For a stronger major project, create a labelled evaluation set of accident and non-accident clips; add temporal collision classification, vehicle tracking, and an evaluation report with precision, recall, false-positive rate, and missed-event rate. Keep a human review step. Do not infer an accident from vehicle detections alone.

## Troubleshooting

- **`python` not found:** reinstall Python with PATH enabled, reopen VS Code, or use `py`.
- **`No module named flask` / `ultralytics`:** activate the virtual environment and run `pip install -r requirements.txt`.
- **Model download fails:** check internet and disk space; use the official Ultralytics model source. Do not download model weights from unknown sites.
- **Camera doesn't open:** close other camera apps and check Windows privacy settings. Try recorded-video mode.
- **Very slow video:** use a shorter 720p clip, close other apps, and ensure the laptop has enough RAM. CPU inference can be slow.
- **Port 5000 is busy:** change `port=5000` at the bottom of `app.py` to `port=5001`, then visit `http://127.0.0.1:5001`.
