import os
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from pyrogram import Client
from pyrogram.types import Message
from youtubesearchpython.__future__ import VideosSearch
import yt_dlp

# --------------------------
# Config (from env or hardcode)
# --------------------------
API_ID = int(os.getenv("API_ID", "123456"))
API_HASH = os.getenv("API_HASH", "abcdef1234567890abcdef1234567890")
BOT_TOKEN = os.getenv("BOT_TOKEN", "123456:ABCDEF")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))

# --------------------------
# Pyrogram client
# --------------------------
tg_client = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --------------------------
# FastAPI app
# --------------------------
app = FastAPI(title="YouTube → Telegram CDN API")

# In-memory DB (video_id → file_id)
video_db = {}

# --------------------------
# Helper functions
# --------------------------
async def search_video(query: str) -> str:
    videos_search = VideosSearch(query, limit=1)
    result = await videos_search.next()
    if result["result"]:
        return result["result"][0]["id"]
    return None

async def download_audio(video_id: str) -> str:
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

async def get_cdn(file_id: int) -> str:
    msg: Message = await tg_client.get_messages(CHANNEL_ID, file_id)
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{msg.audio.file_path}"

# --------------------------
# Lifespan
# --------------------------
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    await tg_client.start()
    await tg_client.send_message(CHANNEL_ID, "✅ Bot started")
    yield
    await tg_client.send_message(CHANNEL_ID, "⛔ Bot stopping")
    await tg_client.stop()

app.router.lifespan_context = lifespan

# --------------------------
# Routes
# --------------------------
@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    # Get video ID
    if "youtube.com" in query or "youtu.be" in query:
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1]
    else:
        video_id = await search_video(query)

    if not video_id:
        return {"error": "No video found"}

    # Check in-memory DB
    if video_id in video_db:
        cdn = await get_cdn(video_db[video_id])
        return {"video_id": video_id, "direct_link": cdn}

    # Download audio
    audio_file = await download_audio(video_id)

    # Upload to Telegram
    msg: Message = await tg_client.send_audio(CHANNEL_ID, audio_file, caption=f"🎵 {video_id}")

    # Save to memory DB
    video_db[video_id] = msg.id

    # Delete local file
    try:
        os.remove(audio_file)
    except:
        pass

    # Return fresh CDN
    cdn = await get_cdn(msg.id)
    return {"video_id": video_id, "direct_link": cdn}

# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1490)
