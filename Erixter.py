import os, re, requests, signal, sys, time, uvicorn, yt_dlp

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

from pyrogram import Client, idle
from urllib.parse import urlparse, parse_qs
from youtubesearchpython.__future__ import VideosSearch




load_dotenv("config.env")


API_ID = os.getenv("API_ID", None)
API_HASH = os.getenv("API_HASH", None)
BOT_TOKEN = os.getenv("BOT_TOKEN", None)
CHANNEL_ID = os.getenv("CHANNEL_ID", None)


app = FastAPI(title="YouTube API")
bot = Client(
    name="Erixter",
    api_id=int(API_ID),
    api_hash=str(API_HASH),
    bot_token=str(BOT_TOKEN),
)

db = {}




def get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "127.0.0.1"

PUBLIC_IP = get_public_ip()




async def download_media(video_id: str, video: bool):
    url = f"https://www.youtube.com/watch?v={video_id}"
    loop = asyncio.get_event_loop()

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








def handle_shutdown(sig, frame):
    print("Server stopped")
    sys.exit(0)

signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


async def start_bot():
    await bot.start()
    try:
        await bot.send_message(
            CHANNEL_ID, "✅ Bot started and is running with API!"
        )
    except Exception as e:
        print(f"Failed to send message: {e}")
    await idle()
    await bot.stop()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    uvicorn.run(app, host="0.0.0.0", port=1489)

