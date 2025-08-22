import os
import sys
import signal
import asyncio
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from pyrogram.types import Message
from pytube import YouTube
from dotenv import load_dotenv
import uvicorn

# Load environment variables
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URL = os.getenv("MONGO_URL")

# Init FastAPI
app = FastAPI(title="YouTube → Telegram CDN API")

# Init MongoDB
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["yt_db"]
collection = db["files"]

# Init Pyrogram Client
tg_client = Client(
    "yt_tg_session",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4,
    in_memory=True
)


# ========== Helper Functions ==========

async def get_video_id(query: str) -> str:
    """Extract video_id from YouTube link or search query"""
    if "youtube.com" in query or "youtu.be" in query:
        yt = YouTube(query)
        return yt.video_id
    yt = YouTube(f"ytsearch:{query}")
    return yt.video_id


async def download_audio(video_id: str) -> str:
    """Download YouTube audio and return file path"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    yt = YouTube(url)
    audio_stream = yt.streams.filter(only_audio=True).first()
    filename = f"{video_id}.mp3"
    file_path = audio_stream.download(filename=filename)
    return file_path


# ========== FastAPI Events ==========

@app.on_event("startup")
async def startup_event():
    await tg_client.start()
    # Bot start হলে channel এ notify করবে
    await tg_client.send_message(CHANNEL_ID, "✅ Bot API started & connected!")


@app.on_event("shutdown")
async def shutdown_event():
    await tg_client.stop()
    mongo_client.close()


# ========== API Endpoints ==========

@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    video_id = await get_video_id(query)

    # MongoDB check
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

    # Save in DB
    await collection.insert_one({
        "video_id": video_id,
        "file_id": sent.audio.file_id
    })

    # Fresh CDN link
    file = await tg_client.get_file(sent.audio.file_id)
    direct_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"

    return {"video_id": video_id, "direct_link": direct_link}


# ========== Graceful Shutdown ==========

def handle_shutdown(sig, frame):
    print("Server stopped")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


# ========== Run Server ==========

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1470)
