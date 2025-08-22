import os
import sys
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from contextlib import asynccontextmanager
from pyrogram import Client
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import yt_dlp
from youtubesearchpython.__future__ import VideosSearch

# --------------------------
# Load ENV
# --------------------------
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

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
    await tg_client.start()
    await tg_client.send_message(CHANNEL_ID, "✅ Bot started and ready to stream!")
    yield
    await tg_client.send_message(CHANNEL_ID, "⛔ Bot shutting down...")
    await tg_client.stop()

app = FastAPI(title="YouTube → Telegram CDN API", lifespan=lifespan)

# --------------------------
# Helper Functions
# --------------------------

async def search_video(query: str) -> str:
    """Search YouTube video ID async"""
    videos_search = VideosSearch(query, limit=1)
    result = await videos_search.next()
    if result["result"]:
        return result["result"][0]["id"]
    return None

async def download_audio(video_id: str) -> str:
    """Download best audio only (no ffmpeg)"""
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

async def get_cdn_link(file_id: str) -> str:
    """Return fresh Telegram CDN link"""
    msg: Message = await tg_client.get_messages(CHANNEL_ID, int(file_id))
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{msg.audio.file_path}"

# --------------------------
# API Endpoints
# --------------------------

@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    # Step 1: Extract video_id
    if "youtube.com" in query or "youtu.be" in query:
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1]
    else:
        video_id = await search_video(query)

    if not video_id:
        return {"error": "No video found"}

    # Step 2: Check DB
    record = await collection.find_one({"video_id": video_id})
    if record:
        cdn_link = await get_cdn_link(record["file_id"])
        return {"video_id": video_id, "direct_link": cdn_link}

    # Step 3: Download audio
    audio_file = await download_audio(video_id)

    # Step 4: Upload to Telegram
    sent: Message = await tg_client.send_audio(
        chat_id=CHANNEL_ID,
        audio=audio_file,
        caption=f"🎵 {video_id}"
    )

    # Step 5: Save to Mongo
    await collection.insert_one({"video_id": video_id, "file_id": sent.id})

    # Step 6: Cleanup local file
    try:
        os.remove(audio_file)
    except Exception as e:
        print(f"Delete error: {e}")

    # Step 7: Return fresh CDN
    cdn_link = await get_cdn_link(sent.id)
    return {"video_id": video_id, "direct_link": cdn_link}

# --------------------------
# Signal Handler
# --------------------------

def handle_shutdown(sig, frame):
    print("Server stopped")
    sys.exit(0)

import signal
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# --------------------------
# Run Server
# --------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1470)
