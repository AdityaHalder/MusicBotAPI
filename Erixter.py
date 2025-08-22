import asyncio
import os
import sys
import signal
import tempfile
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client
from pyrogram.types import Message
from youtubesearchpython import VideosSearch
import yt_dlp
import uvicorn

# ====== CONFIG ======
API_ID = 12380656
API_HASH = "d927c13beaaf5110f25c505b7c071273"
BOT_TOKEN = "6971366762:AAFTWCPAdCu7wVLbJS-VP4EmNPpvFAz13bM"
CHANNEL_ID = -1002865803083
MONGO_URI = "mongodb+srv://erixter:erixter@erixter.mrqltxd.mongodb.net"
DB_NAME = "youtube_files"
COLLECTION_NAME = "videos"

app = FastAPI()
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client[DB_NAME]
collection = db[COLLECTION_NAME]
tg_client = Client("ytbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# -------- Youtube Search --------
async def get_video_id(query: str) -> str:
    if "youtube.com" in query or "youtu.be" in query:
        with yt_dlp.YoutubeDL({}) as ydl:
            info = ydl.extract_info(query, download=False)
            return info["id"]
    else:
        videos_search = VideosSearch(query, limit=1)
        result = videos_search.result()
        return result["result"][0]["id"]


# -------- Youtube Download --------
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


# -------- Stream directly from telegram --------
async def stream_from_telegram(msg_id: int):
    async def file_iterator():
        async with tg_client:
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

    # check mongodb
    record = await collection.find_one({"video_id": video_id})
    if record:
        msg_id = record["msg_id"]
        return await stream_from_telegram(msg_id)

    # if not exists, download audio
    audio_file = await download_audio(video_id)

    # upload to telegram
    async with tg_client:
        sent: Message = await tg_client.send_audio(
            chat_id=CHANNEL_ID,
            audio=audio_file,
            caption=f"VideoID: {video_id}"
        )
        msg_id = sent.id

    # delete local file after upload ✅
    try:
        os.remove(audio_file)
    except Exception as e:
        print(f"Delete error: {e}")

    # save mapping
    await collection.insert_one({"video_id": video_id, "msg_id": msg_id})

    # stream from telegram (direct stream, no local file)
    return await stream_from_telegram(msg_id)


# -------- Graceful Shutdown --------
def handle_shutdown(sig, frame):
    print("⚠️ Server stopped by signal:", sig)
    try:
        mongo_client.close()
    except:
        pass
    sys.exit(0)


signal.signal(signal.SIGINT, handle_shutdown)   # Ctrl+C
signal.signal(signal.SIGTERM, handle_shutdown)  # Docker stop / kill


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1470)
