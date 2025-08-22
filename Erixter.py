import asyncio, os, requests, signal, sys, uvicorn, yt_dlp

from dotenv import load_dotenv
from fastapi import FastAPI, Query
from pyrogram import Client, idle
from youtubesearchpython.__future__ import VideosSearch


load_dotenv("config.env")

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", 0))

bot = Client(
    "Erixter",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

app = FastAPI(title="YouTube API")

stop_event = asyncio.Event()   # 🔑 for graceful shutdown


@app.get("/")
async def root():
    return {"message": "YouTube API is running"}


@app.get("/search")
async def search_videos(query: str):
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


async def start_bot():
    await bot.start()
    try:
        await bot.send_message(CHANNEL_ID, "✅ Bot started and running with API!")
    except Exception as e:
        print(f"Failed to send message: {e}")

    # Wait until shutdown signal
    await stop_event.wait()

    await bot.stop()
    print("Bot stopped cleanly ✅")


async def main():
    asyncio.create_task(start_bot())
    config = uvicorn.Config(app, host="0.0.0.0", port=1489, loop="asyncio")
    server = uvicorn.Server(config)
    await server.serve()

    # when uvicorn stops → signal bot to stop
    stop_event.set()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    def shutdown_handler(sig, frame):
        print("Received shutdown signal...")
        stop_event.set()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    loop.run_until_complete(main())
    loop.close()
