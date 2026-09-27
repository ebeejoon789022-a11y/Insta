import os
import glob
import uuid
import shutil
import base64
from flask import Flask, request, send_file, jsonify, abort
from yt_dlp import YoutubeDL

app = Flask(__name__)

# کلید امنیتی ساده — همین مقدار باید در env variable ‏MUSIC_API_KEY توی Railway
# و در env variable ‏MUSIC_API_KEY توی Cloudflare Worker یکسان باشد.
API_KEY = os.environ.get("MUSIC_API_KEY", "")

DOWNLOAD_DIR = "downloads"
COOKIES_PATH = "cookies.txt"

# اگر کوکی یوتیوب (به‌صورت base64) در env variable ‏YOUTUBE_COOKIES_B64 تنظیم شده باشد،
# آن را در ابتدای اجرا به یک فایل واقعی تبدیل می‌کنیم تا yt-dlp بتواند از آن استفاده کند.
_cookies_b64 = os.environ.get("YOUTUBE_COOKIES_B64", "")
if _cookies_b64:
    try:
        with open(COOKIES_PATH, "wb") as f:
            f.write(base64.b64decode(_cookies_b64))
    except Exception as e:
        print(f"خطا در نوشتن فایل کوکی: {e}")


def check_auth():
    if not API_KEY:
        return  # اگر کلیدی تنظیم نشده باشد، بدون احراز هویت کار می‌کند (فقط برای تست)
    supplied = request.headers.get("X-API-Key", "") or request.args.get("key", "")
    if supplied != API_KEY:
        abort(401, description="کلید API نامعتبر است")


@app.route("/health")
def health():
    return jsonify({"ok": True, "cookies_loaded": os.path.exists(COOKIES_PATH)})


@app.route("/search")
def search():
    check_auth()
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"ok": False, "error": "پارامتر q (اسم آهنگ) لازم است"}), 400

    job_id = uuid.uuid4().hex
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    ydl_opts = {
        "format": "bestaudio/best",
        "default_search": "ytsearch1",
        "outtmpl": os.path.join(job_dir, "%(title)s.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "quiet": True,
        "noplaylist": True,
    }

    if os.path.exists(COOKIES_PATH):
        ydl_opts["cookiefile"] = COOKIES_PATH

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=True)
            if "entries" in info and len(info["entries"]) > 0:
                video_info = info["entries"][0]
            else:
                video_info = info

            title = video_info.get("title", "music")
            uploader = video_info.get("uploader", "")

        mp3_files = glob.glob(os.path.join(job_dir, "*.mp3"))
        if not mp3_files:
            shutil.rmtree(job_dir, ignore_errors=True)
            return jsonify({"ok": False, "error": "فایل صوتی ساخته نشد"}), 500

        mp3_path = mp3_files[0]

        response = send_file(
            mp3_path,
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=f"{title}.mp3",
        )
        response.headers["X-Track-Title"] = title.encode("ascii", "ignore").decode() or "unknown"
        response.headers["X-Track-Uploader"] = uploader.encode("ascii", "ignore").decode() or "unknown"

        @response.call_on_close
        def cleanup():
            shutil.rmtree(job_dir, ignore_errors=True)

        return response

    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
