import os
import json
import logging
import tempfile
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Configuration - Get from environment variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')

# Validate environment variables
if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable not set!")
if not SERVICE_ACCOUNT_JSON:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set!")

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Parse service account credentials
try:
    service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
except json.JSONDecodeError:
    raise ValueError("Failed to parse Google service account JSON")

# Google Drive service setup
def get_drive_service():
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/drive.file']
    )
    return build('drive', 'v3', credentials=credentials)

# Upload to Google Drive and generate shareable link
def upload_to_drive(file_path, file_name):
    try:
        service = get_drive_service()
        
        file_metadata = {'name': file_name}
        media = MediaFileUpload(file_path, resumable=True)
        
        # Upload file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        file_id = file.get('id')
        logger.info(f"File '{file_name}' uploaded to Drive with ID: {file_id}")
        
        # Set public permissions
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(fileId=file_id, body=permission).execute()
        
        # Generate public view link
        return f"https://drive.google.com/file/d/{file_id}/view"
    
    except HttpError as error:
        logger.error(f"Google Drive API error: {error}")
        raise Exception(f"Drive API error: {error.resp.status} - {error.reason}")
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise

# Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('📤 Send me any file to upload it to Google Drive!')

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    tg_file = None

    # Determine file type
    if message.document:
        tg_file = await message.document.get_file()
        original_name = message.document.file_name
    elif message.photo:
        tg_file = await message.photo[-1].get_file()
        original_name = f"photo_{tg_file.file_id}.jpg"
    elif message.video:
        tg_file = await message.video.get_file()
        original_name = message.video.file_name or f"video_{tg_file.file_id}.mp4"
    elif message.audio:
        tg_file = await message.audio.get_file()
        original_name = message.audio.file_name or f"audio_{tg_file.file_id}.mp3"
    else:
        await message.reply_text("❌ Unsupported file type!")
        return

    # Create temp file for download
    suffix = os.path.splitext(original_name)[1] if '.' in original_name else ''
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        download_path = temp_file.name
    
    # Download file
    await tg_file.download_to_drive(download_path)
    logger.info(f"Downloaded file to: {download_path}")
    
    # Upload to Drive
    try:
        drive_link = upload_to_drive(download_path, original_name)
        await message.reply_text(
            f"✅ Successfully uploaded to Google Drive!\n\n"
            f"📄 Filename: `{original_name}`\n"
            f"🔗 Download link: {drive_link}"
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        await message.reply_text(f"❌ Upload failed: {str(e)}")
    finally:
        # Clean up temp file
        if os.path.exists(download_path):
            os.remove(download_path)

def main():
    # Create Application instance
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO,
        handle_file
    ))
    
    # Start polling
    logger.info("Starting bot on Render.com...")
    application.run_polling()

if __name__ == '__main__':
    main()
