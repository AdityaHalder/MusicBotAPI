import asyncio
import os
import tempfile
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from pyrogram.types import Message
from youtubesearchpython import VideosSearch
import yt_dlp
from dotenv import load_dotenv
import uvicorn

# ====== Load config ======
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
MONGO_URI = os.getenv("MONGO_URI")
PORT = int(os.getenv("PORT", 1470))

DB_NAME = "youtube_files"
COLLECTION_NAME = "videos"

# ====== FastAPI, Mongo, Pyrogram ======
app = FastAPI()
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]
tg_client = Client("ytbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# -------- FastAPI lifecycle --------
@app.on_event("startup")
async def startup():
    await tg_client.start()
    print("✅ Pyrogram client started")

@app.on_event("shutdown")
async def shutdown():
    await tg_client.stop()
    mongo_client.close()
    print("🛑 Pyrogram client stopped & DB closed")


# -------- Get YouTube Video ID --------
async def get_video_id(query: str) -> str:
    if "youtube.com" in query or "youtu.be" in query:
        with yt_dlp.YoutubeDL({}) as ydl:
            info = ydl.extract_info(query, download=False)
            return info["id"]
    else:
        videos_search = VideosSearch(query, limit=1)
        result = videos_search.result()
        return result["result"][0]["id"]


# -------- Download YouTube Audio --------
async def download_audio(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    tmpdir = tempfile.mkdtemp()
    output_path = os.path.join(tmpdir, "%(id)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "noplaylist": True,
        "quiet": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    }
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))
    for f in os.listdir(tmpdir):
        return os.path.join(tmpdir, f)


# -------- Stream from Telegram --------
async def stream_from_telegram(msg_id: int):
    async def file_iterator():
        async for chunk in tg_client.stream_media(
            message=msg_id,
            chat_id=CHANNEL_ID,
            limit=1024 * 64
        ):
            yield chunk
    return StreamingResponse(file_iterator(), media_type="audio/mpeg")


# -------- Main Endpoint --------
@app.get("/stream")
async def stream(query: str = Query(..., description="YouTube query or link")):
    video_id = await get_video_id(query)

    # Check MongoDB
    record = await collection.find_one({"video_id": video_id})
    if record:
        return await stream_from_telegram(record["msg_id"])

    # Download YouTube audio
    audio_file = await download_audio(video_id)

    # Upload to Telegram
    sent: Message = await tg_client.send_audio(
        chat_id=CHANNEL_ID,
        audio=audio_file,
        caption=f"VideoID: {video_id}"
    )
    msg_id = sent.id

    # Delete local file
    try:
        os.remove(audio_file)
    except Exception as e:
        print(f"Delete error: {e}")

    # Save to DB
    await collection.insert_one({"video_id": video_id, "msg_id": msg_id})

    # Stream directly from Telegram
    return await stream_from_telegram(msg_id)


# -------- Run Server --------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
