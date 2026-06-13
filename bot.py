import os
import io
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2 import service_account

# ---------------------------------------------------------
# بارگذاری تنظیمات از فایل .env
# ---------------------------------------------------------
load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BOT_TOKEN = os.getenv("BOT_TOKEN")
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
SCOPES = ["https://www.googleapis.com/auth/drive"]

# ---------------------------------------------------------
# ساخت اتصال به گوگل درایو با Service Account
# ---------------------------------------------------------
creds = service_account.Credentials.from_service_account_file(
    "service_account.json", scopes=SCOPES
)
drive_service = build("drive", "v3", credentials=creds)


def upload_to_drive(file_bytes: bytes, filename: str, mime_type: str):
    """آپلود فایل به گوگل درایو و بازگرداندن اطلاعات فایل آپلود شده"""
    file_metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return file


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دریافت فایل از تلگرام و ارسال آن به گوگل درایو"""
    msg = update.message
    file_obj = None
    filename = "file"
    mime_type = "application/octet-stream"

    if msg.document:
        file_obj = await msg.document.get_file()
        filename = msg.document.file_name or f"document_{file_obj.file_unique_id}"
        mime_type = msg.document.mime_type or mime_type

    elif msg.photo:
        photo = msg.photo[-1]  # بالاترین کیفیت
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
        await msg.reply_text("⚠️ نوع این فایل پشتیبانی نمی‌شود.")
        return

    await msg.reply_text(f"⬇️ در حال دانلود {filename} ...")

    file_bytes = await file_obj.download_as_bytearray()

    await msg.reply_text("☁️ در حال آپلود در گوگل درایو ...")

    try:
        result = upload_to_drive(bytes(file_bytes), filename, mime_type)
        link = result.get("webViewLink", "لینکی موجود نیست")
        await msg.reply_text(f"✅ آپلود با موفقیت انجام شد!\n📄 {filename}\n🔗 {link}")
    except Exception as e:
        logging.error(f"خطا در آپلود: {e}")
        await msg.reply_text(f"❌ آپلود ناموفق بود: {e}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(
        MessageHandler(
            filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO | filters.VOICE,
            handle_file,
        )
    )

    logging.info("ربات روشن شد و در حال انتظار برای فایل‌هاست ...")
    app.run_polling()


if __name__ == "__main__":
    main()
