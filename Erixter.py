import asyncio, os, re, requests, signal
import sys, time, yt_dlp, uvicorn

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from pyrogram import Client, filters
from contextlib import asynccontextmanager
from urllib.parse import urlparse, parse_qs
from motor.motor_asyncio import AsyncIOMotorClient
from youtubesearchpython.__future__ import VideosSearch



# =======================
# Load ENV
# =======================
load_dotenv("config.env")

API_ID = int(os.getenv("API_ID", 0))
API_HASH = str(os.getenv("API_HASH", ""))
BOT_TOKEN = str(os.getenv("BOT_TOKEN", ""))
MONGO_URL = str(os.getenv("MONGO_URL", ""))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

# =======================
# Init Pyrogram Bot
# =======================
bot = Client(
    "Erixter",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


try:
    mdb = AsyncIOMotorClient(MONGO_URL)
except Exception:
    print("⚠️ 'MONGO_URL' - is not valid !!")
    sys.exit()
    
mongodb = mdb.erixterapitest


# =======================
# Utils
# =======================
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
        download_format = (
            "bestaudio/best"
            if not video
            else "(bestvideo[height<=?720][width<=?1280][ext=mp4])+(bestaudio[ext=m4a])"
        )

        ydl_opts = {
            "format": download_format,
            "outtmpl": "downloads/%(id)s.%(ext)s",
            "geo_bypass": True,
            "nocheckcertificate": True,
            "quiet": True,
            "no_warnings": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            filepath = os.path.join("downloads", f"{info['id']}.{info['ext']}")

            if os.path.exists(filepath):
                return filepath

            ydl.download([url])
            return filepath

    return await loop.run_in_executor(None, media_dl)


# =======================
# FastAPI lifespan
# =======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
       await mdb.admin.command('ping')
    except Exception:
        print("⚠️ 'MONGO_URL' - is not valid !!")
        sys.exit()
        
    # Startup
    await bot.start()
    try:
        await bot.send_message(
            CHANNEL_ID, "✅ Bot started and API is running!"
        )
    except Exception as e:
        print(f"Failed to notify channel: {e}")

    yield  # <-- API runs here

    # --- Shutdown ---
    print("Shutting down...")
    await bot.stop()   # this is enough
    print("Bot stopped")
    

# =======================
# FastAPI app
# =======================
app = FastAPI(title="YouTube API", lifespan=lifespan)

# optional CORS
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
async def search_videos(query: str = Query(..., description="Search query")):
    try:
        videos_search = VideosSearch(query, limit=1)
        result = await videos_search.next()
        videos = result.get("result", [])

        if not videos:
            return {}

        v = videos[0]
        return {
            "id": v["id"],
            "title": v["title"],
            "duration": v.get("duration"),
            "channel": v["channel"]["name"] if "channel" in v else None,
            "thumbnail": v["thumbnails"][0]["url"] if v.get("thumbnails") else None,
            "stream_url": None
        }

    except Exception:
        return {}




@bot.on_message(filters.command("start") & filters.private)
async def start_message_private(client, message):
    return await message.reply_text(
        f"**Hello, {message.from_user.mention}**"
    )









if __name__ == "__main__":
    uvicorn.run("Erixter:app", host="0.0.0.0", port=1489, reload=False)

