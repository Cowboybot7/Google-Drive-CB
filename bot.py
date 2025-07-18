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

# Validate environment variables
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SERVICE_ACCOUNT_JSON = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')  # New environment variable

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN environment variable not set!")
if not SERVICE_ACCOUNT_JSON:
    raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set!")
if not DRIVE_FOLDER_ID:
    raise RuntimeError("GOOGLE_DRIVE_FOLDER_ID environment variable not set!")

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Parse service account credentials
try:
    service_account_info = json.loads(SERVICE_ACCOUNT_JSON)
except json.JSONDecodeError as e:
    logger.error("Failed to parse service account JSON: %s", e)
    raise

# Google Drive service setup
def get_drive_service():
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/drive.file']
    )
    return build('drive', 'v3', credentials=credentials)

# Upload to Google Drive
def upload_to_drive(file_path, file_name):
    try:
        service = get_drive_service()
        
        file_metadata = {
            'name': file_name,
            'parents': [DRIVE_FOLDER_ID]  # Upload to specific folder
        }
        media = MediaFileUpload(file_path, resumable=True)
        
        # Upload file
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id'
        ).execute()
        file_id = file.get('id')
        logger.info(f"Uploaded '{file_name}' to Drive. ID: {file_id}")
        
        # Set public permissions
        permission = {'type': 'anyone', 'role': 'reader'}
        service.permissions().create(
            fileId=file_id,
            body=permission
        ).execute()
        
        return f"https://drive.google.com/file/d/{file_id}/view"
    
    except HttpError as error:
        logger.error(f"Google Drive API error: {error}")
        raise Exception(f"Drive API error: {error.resp.status} - {error.reason}")
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise

# Telegram Handlers (unchanged)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('📤 Send me a file to upload to Google Drive!')

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    
    # Get file based on type
    if message.document:
        file_obj = message.document
        tg_file = await file_obj.get_file()
        original_name = file_obj.file_name
    elif message.photo:
        file_obj = message.photo[-1]
        tg_file = await file_obj.get_file()
        original_name = f"photo_{file_obj.file_id}.jpg"
    elif message.video:
        file_obj = message.video
        tg_file = await file_obj.get_file()
        original_name = file_obj.file_name or f"video_{file_obj.file_id}.mp4"
    elif message.audio:
        file_obj = message.audio
        tg_file = await file_obj.get_file()
        original_name = file_obj.file_name or f"audio_{file_obj.file_id}.mp3"
    else:
        await message.reply_text("❌ Unsupported file type!")
        return

    # Create temp file
    suffix = os.path.splitext(original_name)[1] if '.' in original_name else ''
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        download_path = temp_file.name
    
    # Download file
    await tg_file.download_to_drive(download_path)
    logger.info(f"Downloaded file to temp path: {download_path}")
    
    # Upload to Drive
    try:
        drive_link = upload_to_drive(download_path, original_name)
        await message.reply_text(
            f"✅ File uploaded to Google Drive!\n\n"
            f"📄 Filename: {original_name}\n"
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
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(
        filters.Document.ALL | filters.PHOTO | filters.VIDEO | filters.AUDIO,
        handle_file
    ))
    logger.info("Bot is running on Render.com...")
    application.run_polling()

if __name__ == '__main__':
    main()
