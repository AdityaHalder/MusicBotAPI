import asyncio, os, re, requests, signal
import sys, time, uvicorn, yt_dlp

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

mongodb = mdb.erixterapitest

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
        opts = {
            "format": fmt,
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filepath = os.path.join("downloads", f"{info['id']}.{info['ext']}")
            if os.path.exists(filepath):
                return filepath
            ydl.download([url])
            return filepath

    return await loop.run_in_executor(None, media_dl)




def clean_mongo_doc(doc: dict) -> dict:
    if not doc:
        return {}
    doc = dict(doc)
    doc.pop("_id", None)  # remove ObjectId
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
async def search_videos(query: str = Query(...), video: bool = Query(False)):
    db = video_db if video else audio_db

    videos_search = VideosSearch(query, limit=1)
    result = await videos_search.next()
    videos = result.get("result", [])
    if not videos:
        return {}

    v = videos[0]
    vid_id = v["id"]

    # --- Check if already in DB
    existing = await db.find_one({"id": vid_id})
    if existing:
        return clean_mongo_doc(existing)

    # --- Download Media
    filepath = await download_media(vid_id, video)

    tg_msg = await bot.send_document(
        CHANNEL_ID,
        filepath,
        caption=v["title"],
        file_name=f"{vid_id}{os.path.splitext(filepath)[1]}",
    )

    data = {
        "id": vid_id,
        "title": v["title"],
        "duration": v.get("duration"),
        "channel": v["channel"]["name"] if "channel" in v else None,
        "thumbnail": v["thumbnails"][0]["url"] if v.get("thumbnails") else None,
        "stream_url": f"https://t.me/c/{str(CHANNEL_ID)[4:]}/{tg_msg.id}",
    }

    await db.insert_one(data)
    if os.path.exists(filepath): os.remove(filepath)
    return data


@bot.on_message(filters.command("start") & filters.private)
async def start_message_private(client, message):
    return await message.reply_text(f"**Hello, {message.from_user.mention}**")


if __name__ == "__main__":
    uvicorn.run("Erixter:app", host="0.0.0.0", port=1489, reload=False)

