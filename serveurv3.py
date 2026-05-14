import os
import re
import threading
import sys
import subprocess

def install(pkg):
    subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)

try:
    from flask import Flask, request, jsonify, send_from_directory
except ImportError:
    install("flask"); from flask import Flask, request, jsonify, send_from_directory

try:
    from flask_cors import CORS
except ImportError:
    install("flask-cors"); from flask_cors import CORS

try:
    import yt_dlp
except ImportError:
    install("yt-dlp"); import yt_dlp

app = Flask(__name__, static_folder=".")
CORS(app)

DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "VideoDownloader")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

progress_store = {}

def strip_ansi(text):
    """Retire les codes couleur ANSI d'une chaîne."""
    return re.sub(r'\x1b\[[0-9;]*m', '', str(text)).strip()


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/status")
def status():
    return jsonify({"ready": True, "download_dir": DOWNLOAD_DIR, "ytdlp": True})


@app.route("/api/info", methods=["POST"])
def get_info():
    data = request.json
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL manquante"}), 400

    try:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = []
        seen = set()

        for f in info.get("formats", []):
            ext = f.get("ext", "")
            height = f.get("height")
            acodec = f.get("acodec", "none")
            vcodec = f.get("vcodec", "none")

            if vcodec and vcodec != "none" and height:
                label = f"{height}p ({ext})"
                if label not in seen:
                    seen.add(label)
                    formats.append({
                        "format_id": f["format_id"],
                        "label": label,
                        "height": height,
                        "ext": ext,
                        "type": "video"
                    })
            elif acodec and acodec != "none" and (not vcodec or vcodec == "none"):
                label = f"Audio ({ext})"
                if label not in seen:
                    seen.add(label)
                    formats.append({
                        "format_id": f["format_id"],
                        "label": label,
                        "height": 0,
                        "ext": ext,
                        "type": "audio"
                    })

        formats.sort(key=lambda x: x["height"], reverse=True)

        if not formats:
            formats.append({
                "format_id": "best",
                "label": "Meilleur format disponible",
                "height": 0,
                "ext": "mp4",
                "type": "video"
            })

        return jsonify({
            "title": info.get("title", "Vidéo"),
            "thumbnail": info.get("thumbnail", ""),
            "duration": info.get("duration", 0),
            "uploader": info.get("uploader", ""),
            "formats": formats[:10]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def download():
    data = request.json
    url = data.get("url", "").strip()
    format_id = data.get("format_id", "bestvideo+bestaudio/best")
    task_id = data.get("task_id", "default")

    if not url:
        return jsonify({"error": "URL manquante"}), 400

    progress_store[task_id] = {"status": "starting", "percent": 0, "speed": "", "eta": ""}

    def progress_hook(d):
        if d["status"] == "downloading":
            # Utilise downloaded_bytes / total_bytes pour un % fiable
            downloaded = d.get("downloaded_bytes", 0) or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0

            if total > 0:
                pct = round((downloaded / total) * 100, 1)
            else:
                pct = progress_store[task_id].get("percent", 0)

            # Nettoie les codes ANSI sur vitesse et ETA
            speed = strip_ansi(d.get("_speed_str", ""))
            eta = strip_ansi(d.get("_eta_str", ""))

            progress_store[task_id] = {
                "status": "downloading",
                "percent": pct,
                "speed": speed,
                "eta": eta
            }

        elif d["status"] == "finished":
            progress_store[task_id] = {
                "status": "merging",
                "percent": 99,
                "speed": "",
                "eta": "Fusion en cours..."
            }

    def run_download():
        try:
            fmt = format_id if format_id else "bestvideo+bestaudio/best"
            ydl_opts = {
                "format": fmt,
                "outtmpl": os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s"),
                "merge_output_format": "mp4",
                "progress_hooks": [progress_hook],
                "quiet": False,
                "no_warnings": True,
                "no_color": True,
                # Remplacer la section postprocessors par celle-ci :
                "postprocessors": [{
                    "key": "FFmpegVideoConvertor",
                    "preferedformat": "mp4",
                }],
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            progress_store[task_id] = {"status": "done", "percent": 100, "speed": "", "eta": ""}

        except Exception as e:
            progress_store[task_id] = {
                "status": "error", "percent": 0,
                "speed": "", "eta": "", "message": str(e)
            }

    thread = threading.Thread(target=run_download, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id, "download_dir": DOWNLOAD_DIR})


@app.route("/api/progress/<task_id>")
def get_progress(task_id):
    return jsonify(progress_store.get(task_id, {"status": "unknown", "percent": 0}))


if __name__ == "__main__":
    print(f"📁 Dossier de téléchargement : {DOWNLOAD_DIR}")
    print("🚀 Serveur démarré sur http://localhost:5000\n")
    app.run(debug=False, port=5000)