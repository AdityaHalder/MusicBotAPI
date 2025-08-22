import os
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import RedirectResponse
from pyrogram import Client
from pyrogram.types import Message
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython.__future__ import VideosSearch
import yt_dlp
from dotenv import load_dotenv
from contextlib import asynccontextmanager

# --------------------------
# Load config
# --------------------------
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# --------------------------
# MongoDB
# --------------------------
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["musicbot"]
collection = db["files"]

# --------------------------
# Pyrogram client
# --------------------------
tg_client = Client(
    "musicbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# --------------------------
# FastAPI app
# --------------------------
app = FastAPI(title="MusicBot API")

# --------------------------
# Helper functions
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

async def get_cdn_link(file_id: int) -> str:
    """Return fresh Telegram CDN link"""
    msg: Message = await tg_client.get_messages(CHANNEL_ID, file_id)
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{msg.audio.file_path}"

# --------------------------
# Lifespan manager
# --------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await tg_client.start()
    await tg_client.send_message(CHANNEL_ID, "✅ MusicBot API Started")
    yield
    await tg_client.send_message(CHANNEL_ID, "⛔ MusicBot API Stopping")
    await tg_client.stop()

app.router.lifespan_context = lifespan

# --------------------------
# /stream endpoint
# --------------------------
@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    # Step 1: Get video ID
    if "youtube.com" in query or "youtu.be" in query:
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1]
    else:
        video_id = await search_video(query)
    if not video_id:
        return {"error": "No video found"}

    # Step 2: Check MongoDB
    record = await collection.find_one({"video_id": video_id})
    if record:
        cdn_link = await get_cdn_link(record["file_id"])
        return RedirectResponse(url=cdn_link)

    # Step 3: Download audio
    audio_file = await download_audio(video_id)

    # Step 4: Upload to Telegram
    msg: Message = await tg_client.send_audio(CHANNEL_ID, audio_file, caption=f"🎵 {video_id}")

    # Step 5: Save to MongoDB
    await collection.insert_one({"video_id": video_id, "file_id": msg.id})

    # Step 6: Cleanup local file
    try:
        os.remove(audio_file)
    except:
        pass

    # Step 7: Redirect to Telegram CDN
    cdn_link = await get_cdn_link(msg.id)
    return RedirectResponse(url=cdn_link)

# --------------------------
# /info endpoint
# --------------------------
@app.get("/info")
async def info(query: str = Query(..., description="YouTube query or link")):
    if "youtube.com" in query or "youtu.be" in query:
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1]
    else:
        videos_search = VideosSearch(query, limit=1)
        result = await videos_search.next()
        if not result["result"]:
            return {"error": "No video found"}
        video_id = result["result"][0]["id"]

    # Use yt-dlp to fetch metadata
    ydl_opts = {"quiet": True, "skip_download": True}
    loop = asyncio.get_event_loop()
    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "uploader": info.get("uploader")
            }
    return await loop.run_in_executor(None, run_ydl)

# --------------------------
# Signal handler
# --------------------------
import signal, sys
def handle_shutdown(sig, frame):
    print("Server stopped")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# --------------------------
# Run server
# --------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1490)
