import os
import io
import json
import logging
import asyncio
from datetime import datetime

import requests
from telegram import Bot
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.environ["BOT_TOKEN"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
OFFSET_FILE = "offset.txt"
STATS_FILE = "stats.json"

# برای کامند /now (تریگر دستی ورک‌فلو)
GH_TOKEN = os.environ.get("GH_PAT")  # Personal Access Token
GH_REPO = os.environ.get("GH_REPO")  # مثلا "username/tg-drive-bot"
GH_WORKFLOW_FILE = "bot.yml"

# ---------------------------------------------------------
# اتصال به گوگل درایو
# ---------------------------------------------------------
oauth_info = json.loads(os.environ["GOOGLE_OAUTH_JSON"])
creds = Credentials(
    token=None,
    refresh_token=oauth_info["refresh_token"],
    client_id=oauth_info["client_id"],
    client_secret=oauth_info["client_secret"],
    token_uri="https://oauth2.googleapis.com/token",
    scopes=SCOPES,
)
drive_service = build("drive", "v3", credentials=creds)


def load_offset():
    if os.path.exists(OFFSET_FILE):
        content = open(OFFSET_FILE).read().strip()
        if content.lstrip("-").isdigit():
            return int(content)
    return None


def save_offset(offset):
    if offset is not None:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))


def load_stats():
    if os.path.exists(STATS_FILE):
        try:
            return json.load(open(STATS_FILE))
        except Exception:
            pass
    return {"total_files": 0, "last_file": None, "last_time": None}


def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, ensure_ascii=False)


def upload_to_drive(file_bytes, filename, mime_type):
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    return drive_service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()


def drive_folder_link():
    return f"https://drive.google.com/drive/folders/{DRIVE_FOLDER_ID}"


def trigger_workflow_now():
    """با فراخوانی GitHub API، اجرای فوری ورک‌فلو را شروع می‌کند"""
    if not GH_TOKEN or not GH_REPO:
        return False, "GH_PAT یا GH_REPO تنظیم نشده"

    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{GH_WORKFLOW_FILE}/dispatches"
    headers = {
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
    }
    payload = {"ref": "main"}

    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    if resp.status_code == 204:
        return True, None
    return False, f"{resp.status_code} - {resp.text}"


async def main():
    offset = load_offset()
    stats = load_stats()

    async with Bot(token=BOT_TOKEN) as bot:
        updates = await bot.get_updates(offset=offset, timeout=10)

        for update in updates:
            offset = update.update_id + 1
            msg = update.message
            if not msg:
                continue

            text = (msg.text or "").strip()

            # ------------------------------
            # دستورات متنی
            # ------------------------------
            if text == "/start":
                await bot.send_message(
                    chat_id=msg.chat_id,
                    text=(
                        "👋 سلام!\n"
                        "هر فایلی (سند، عکس، ویدیو، صدا، ویس) برام بفرستی، "
                        "خودکار توی گوگل درایوت ذخیره می‌کنم.\n\n"
                        "برای دیدن دستورات: /help"
                    ),
                )
                continue

            if text == "/help":
                await bot.send_message(
                    chat_id=msg.chat_id,
                    text=(
                        "📋 دستورات:\n"
                        "/start - معرفی ربات\n"
                        "/help - همین لیست\n"
                        "/status - آخرین فایل آپلودشده\n"
                        "/stats - تعداد کل فایل‌های آپلودشده\n"
                        "/folder - لینک پوشه گوگل درایو\n"
                        "/now - چک فوری (برای کارهای عجله‌ای)\n\n"
                        "⏱ توجه: بدون /now، چک کردن فایل جدید هر چند دقیقه یک‌بار انجام می‌شود."
                    ),
                )
                continue

            if text == "/status":
                if stats["last_file"]:
                    await bot.send_message(
                        chat_id=msg.chat_id,
                        text=(
                            f"📄 آخرین فایل: {stats['last_file']}\n"
                            f"🕒 زمان: {stats['last_time']}"
                        ),
                    )
                else:
                    await bot.send_message(chat_id=msg.chat_id, text="هنوز فایلی آپلود نشده.")
                continue

            if text == "/stats":
                await bot.send_message(
                    chat_id=msg.chat_id,
                    text=f"📊 تعداد کل فایل‌های آپلودشده: {stats['total_files']}",
                )
                continue

            if text == "/folder":
                await bot.send_message(
                    chat_id=msg.chat_id,
                    text=f"📁 پوشه گوگل درایو:\n{drive_folder_link()}",
                )
                continue

            if text == "/now":
                # پیام انتظار انگلیسی، طبق درخواست
                await bot.send_message(
                    chat_id=msg.chat_id,
                    text="⏳ Waiting for upload... please send your file now.",
                )
                ok, err = trigger_workflow_now()
                if not ok:
                    await bot.send_message(
                        chat_id=msg.chat_id, text=f"⚠️ چک فوری شروع نشد: {err}"
                    )
                continue

            # ------------------------------
            # فایل‌ها
            # ------------------------------
            file_obj = None
            filename = "file"
            mime_type = "application/octet-stream"

            if msg.document:
                file_obj = await msg.document.get_file()
                filename = msg.document.file_name or f"document_{file_obj.file_unique_id}"
                mime_type = msg.document.mime_type or mime_type
            elif msg.photo:
                photo = msg.photo[-1]
                file_obj = await photo.get_file()
                filename = f"photo_{photo.file_unique_id}.jpg"
                mime_type = "image/jpeg"
            elif msg.video:
                file_obj = await msg.video.get_file()
                filename = msg.video.file_name or f"video_{file_obj.file_unique_id}.mp4"
                mime_type = msg.video.mime_type or "video/mp4"
            elif msg.audio:
                file_obj = await msg.audio.get_file()
                filename = msg.audio.file_name or f"audio_{file_obj.file_unique_id}.mp3"
                mime_type = msg.audio.mime_type or "audio/mpeg"
            elif msg.voice:
                file_obj = await msg.voice.get_file()
                filename = f"voice_{file_obj.file_unique_id}.ogg"
                mime_type = "audio/ogg"

            if not file_obj:
                continue

            try:
                file_bytes = await file_obj.download_as_bytearray()
                result = upload_to_drive(bytes(file_bytes), filename, mime_type)
                link = result.get("webViewLink", "")

                stats["total_files"] += 1
                stats["last_file"] = filename
                stats["last_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")

                await bot.send_message(chat_id=msg.chat_id, text=f"✅ {filename}\n🔗 {link}")
            except Exception as e:
                logging.error(f"upload error: {e}")
                await bot.send_message(chat_id=msg.chat_id, text=f"❌ خطا: {e}")

    save_offset(offset)
    save_stats(stats)


if __name__ == "__main__":
    asyncio.run(main())
