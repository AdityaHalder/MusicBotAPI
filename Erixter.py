import aiohttp, asyncio, os, re, requests, signal
import sys, time, uvicorn, yt_dlp

from bson import ObjectId
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pyrogram import Client, filters
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython.__future__ import VideosSearch


load_dotenv("config.env")

API_ID = int(os.getenv("API_ID", 0))
API_HASH = str(os.getenv("API_HASH", ""))
BOT_TOKEN = str(os.getenv("BOT_TOKEN", ""))
MONGO_URL = str(os.getenv("MONGO_URL", ""))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

bot = Client(
    "Erixter",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

try:
    mdb = AsyncIOMotorClient(MONGO_URL)
except Exception:
    print("⚠️ Invalid 'MONGO_URL'")
    sys.exit()

mongodb = mdb.erixter_api_tests

audio_db = mongodb.audio_db
video_db = mongodb.video_db


def get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "127.0.0.1"

PUBLIC_IP = get_public_ip()


async def download_media(video_id: str, video: bool):
    url = f"https://www.youtube.com/watch?v={video_id}"
    loop = asyncio.get_running_loop()

    def media_dl():
        fmt = (
            "bestaudio/best"
            if not video
            else "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])"
        )
        ext = "mp3" if not video else "mp4"
        opts = {
            "format": fmt,
            "outtmpl": f"downloads/%(id)s.{ext}",
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filepath = os.path.join("downloads", f"{info['id']}.{ext}")
            if os.path.exists(filepath):
                return filepath
            ydl.download([url])
            return filepath

    return await loop.run_in_executor(None, media_dl)


def clean_mongo(doc: dict) -> dict:
    if not doc:
        return {}
    doc = dict(doc)
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])  # or remove completely
        doc.pop("_id")   # if you don’t want it at all
    return doc


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await mdb.admin.command("ping")
    except Exception:
        print("⚠️ Invalid 'MONGO_URL'")
        sys.exit()

    await bot.start()
    try:
        await bot.send_message(CHANNEL_ID, "✅ Bot started and API is running!")
    except Exception as e:
        print(f"Failed to notify channel: {e}")

    yield

    print("Shutting down...")
    await bot.stop()
    print("Bot stopped")


app = FastAPI(title="YouTube API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "YouTube API is running"}


@app.get("/search")
async def search_videos(
    query: str = Query(..., description="Search term"),
    video: bool = Query(False, description="True for video, False for audio"),
):
    # 1. Pick the right collection
    db = video_db if video else audio_db

    # 2. Search YouTube
    result = await VideosSearch(query, limit=1).next()
    items = result.get("result", [])
    if not items:
        return {}

    v = items[0]
    vid_id = v["id"]
    duration_str = v.get("duration", "0:00")

    # 3. Return cached doc if found
    cached = await db.find_one({"id": vid_id})
    if cached:
        return clean_mongo(cached)

    # 4. Parse duration into seconds
    parts = list(map(int, duration_str.split(":")))
    if len(parts) == 3:
        hrs, mins, secs = parts
    elif len(parts) == 2:
        hrs, mins, secs = 0, parts[0], parts[1]
    else:
        hrs, mins, secs = 0, 0, parts[0]
    duration_seconds = hrs * 3600 + mins * 60 + secs

    # 5. Download locally
    filepath = await download_media(vid_id, video)

    # 6. Build caption with artist & duration
    caption = (
        f"{v['title']}\n"
        f"Artist: @ErixterNetwork\n"
        f"Duration: {duration_str}"
    )

    # 7. Send as document (force document mode)
    tg_msg = await bot.send_document(
        chat_id=CHANNEL_ID,
        document=filepath,
        caption=caption,
        file_name=f"{vid_id}{os.path.splitext(filepath)[1]}",
    )

    # 8. Extract and cache the file_id
    tg_media_file = (
        tg_msg.document
        or tg_msg.audio
        or tg_msg.video
    )
    file_id = tg_media_file.file_id

    # 9. Build Telegram CDN URL
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
        ) as resp:
            data = await resp.json()
            file_path = data["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"


    # 10. Persist metadata
    record = {
        "id": vid_id,
        "title": v["title"],
        "artist": "@ErixterNetwork",
        "duration_str": duration_str,
        "duration_sec": duration_seconds,
        "file_id": file_id,
        "channel": v.get("channel", {}).get("name"),
        "thumbnail": v.get("thumbnails", [{}])[0].get("url"),
        "stream_url": f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{tg_msg.id}",
        "download_url": download_url,
    }
    await db.insert_one(record)
    
    # 11. Cleanup
    try:
        os.remove(filepath)
    except OSError:
        pass

    return clean_mongo(record)



@bot.on_message(filters.command("start") & filters.private)
async def start_message_private(client, message):
    return await message.reply_text(f"**Hello, {message.from_user.mention}**")


if __name__ == "__main__":
    uvicorn.run("Erixter:app", host="0.0.0.0", port=1489, reload=False)

