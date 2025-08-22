import os
import sys
import signal
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from contextlib import asynccontextmanager
from pyrogram import Client
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import yt_dlp

# --------------------------
# Load ENV
# --------------------------
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URL = os.getenv("MONGO_URL")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

# --------------------------
# Mongo + Pyrogram
# --------------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["youtube_db"]
collection = db["files"]

tg_client = Client(
    "tg_client",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --------------------------
# Lifespan Manager
# --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await tg_client.start()
    await tg_client.send_message(CHANNEL_ID, "✅ Bot started and ready to stream!")
    yield
    # Shutdown
    await tg_client.send_message(CHANNEL_ID, "⛔ Bot shutting down...")
    await tg_client.stop()

# --------------------------
# FastAPI App
# --------------------------
app = FastAPI(title="YouTube → Telegram CDN API", lifespan=lifespan)

# --------------------------
# Helper Functions
# --------------------------

async def get_video_id(query: str) -> str:
    """Extract YouTube video ID using yt_dlp"""
    ydl_opts = {"quiet": True, "skip_download": True}
    loop = asyncio.get_event_loop()

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            return info.get("id")

    return await loop.run_in_executor(None, run_ydl)


async def download_audio(video_id: str) -> str:
    """Download YouTube best audio only (no ffmpeg)"""
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": f"{video_id}.%(ext)s",
        "quiet": True,
    }
    loop = asyncio.get_event_loop()

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)
            return ydl.prepare_filename(info)

    return await loop.run_in_executor(None, run_ydl)


# --------------------------
# API Endpoints
# --------------------------

@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    video_id = await get_video_id(query)

    # Check DB
    record = await collection.find_one({"video_id": video_id})
    if record:
        file = await tg_client.get_file(record["file_id"])
        direct_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
        return {"video_id": video_id, "direct_link": direct_link}

    # Download YouTube audio
    audio_file = await download_audio(video_id)

    # Upload to Telegram
    sent: Message = await tg_client.send_audio(
        chat_id=CHANNEL_ID,
        audio=audio_file,
        caption=f"VideoID: {video_id}"
    )

    # Local file delete
    try:
        os.remove(audio_file)
    except Exception as e:
        print(f"Delete error: {e}")

    # Save to DB (video_id + file_id only)
    await collection.insert_one({
        "video_id": video_id,
        "file_id": sent.audio.file_id
    })

    # Fresh CDN link
    file = await tg_client.get_file(sent.audio.file_id)
    direct_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    return {"video_id": video_id, "direct_link": direct_link}


# --------------------------
# Signal Handler
# --------------------------

def handle_shutdown(sig, frame):
    print("Server stopped")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# --------------------------
# Run Server
# --------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1470)
