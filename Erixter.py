import os
import asyncio
import uvicorn
from fastapi import FastAPI, Query
from pymongo import MongoClient
from pyrogram import Client
from youtubesearchpython import VideosSearch
import yt_dlp
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load .env variables
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")

# MongoDB
mongo = MongoClient(MONGO_URL)
db = mongo["yt_stream"]
collection = db["files"]

# Pyrogram client (global, start once)
tg_client = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# FastAPI app
app = FastAPI()


# ---------- Helper Functions ----------
async def search_video(query: str) -> str:
    """Search YouTube video ID from query"""
    videos_search = VideosSearch(query, limit=1)
    result = await videos_search.next()
    if result["result"]:
        return result["result"][0]["id"]
    return None


async def download_audio(video_id: str) -> str:
    """Download best audio (no ffmpeg)"""
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


async def get_tg_cdn(file_id: str) -> str:
    """Generate Telegram CDN link from file_id"""
    file = await tg_client.get_messages(CHANNEL_ID, int(file_id))
    file_info = await file.download()
    # Actually we don’t need local file, just CDN
    cdn = (await tg_client.get_messages(CHANNEL_ID, int(file_id))).link
    return cdn


# ---------- FastAPI Lifespan ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await tg_client.start()
    await tg_client.send_message(CHANNEL_ID, "✅ Bot started")
    yield
    await tg_client.send_message(CHANNEL_ID, "⛔ Bot shutting down...")
    await tg_client.stop()


app.router.lifespan_context = lifespan


# ---------- Routes ----------
@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    # Step 1: find video_id
    if "youtube.com" in query or "youtu.be" in query:
        video_id = query.split("v=")[-1].split("&")[0] if "v=" in query else query.split("/")[-1]
    else:
        video_id = await search_video(query)

    if not video_id:
        return {"error": "No video found"}

    # Step 2: check DB
    record = collection.find_one({"video_id": video_id})
    if record:
        file_id = record["file_id"]
        msg = await tg_client.get_messages(CHANNEL_ID, int(file_id))
        cdn = msg.link
        return {"video_id": video_id, "direct_link": cdn}

    # Step 3: download
    file_path = await download_audio(video_id)

    # Step 4: upload to Telegram
    msg = await tg_client.send_audio(CHANNEL_ID, file_path, caption=f"🎵 {video_id}")

    # Step 5: save to DB
    collection.insert_one({"video_id": video_id, "file_id": msg.id})

    # Step 6: cleanup
    try:
        os.remove(file_path)
    except Exception:
        pass

    return {"video_id": video_id, "direct_link": msg.link}


# ---------- Run ----------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1470)
