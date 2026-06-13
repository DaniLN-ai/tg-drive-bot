import os
import io
import json
import logging
import asyncio

from telegram import Bot
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.environ["BOT_TOKEN"]
DRIVE_FOLDER_ID = os.environ["DRIVE_FOLDER_ID"]
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
OFFSET_FILE = "offset.txt"

# ---------------------------------------------------------
# اتصال به گوگل درایو با همان OAuth قبلی
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
    """آخرین update_id پردازش‌شده را از فایل می‌خواند"""
    if os.path.exists(OFFSET_FILE):
        content = open(OFFSET_FILE).read().strip()
        if content.lstrip("-").isdigit():
            return int(content)
    return None


def save_offset(offset):
    if offset is not None:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(offset))


def upload_to_drive(file_bytes, filename, mime_type):
    file_metadata = {"name": filename, "parents": [DRIVE_FOLDER_ID]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    return drive_service.files().create(
        body=file_metadata, media_body=media, fields="id, webViewLink"
    ).execute()


async def main():
    offset = load_offset()

    async with Bot(token=BOT_TOKEN) as bot:
        updates = await bot.get_updates(offset=offset, timeout=10)

        for update in updates:
            offset = update.update_id + 1
            msg = update.message
            if not msg:
                continue

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
                await bot.send_message(chat_id=msg.chat_id, text=f"✅ {filename}\n🔗 {link}")
            except Exception as e:
                logging.error(f"upload error: {e}")
                await bot.send_message(chat_id=msg.chat_id, text=f"❌ خطا: {e}")

    save_offset(offset)


if __name__ == "__main__":
    asyncio.run(main())
