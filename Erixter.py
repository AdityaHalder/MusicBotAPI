import re, requests, signal, sys, time, uvicorn, yt_dlp

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

from urllib.parse import urlparse, parse_qs
from youtubesearchpython.__future__ import VideosSearch


app = FastAPI(title="YouTube API")


db = {}


def get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "127.0.0.1"

PUBLIC_IP = get_public_ip()



@app.get("/")
async def root():
    return {"message": "YouTube API is running"}







@app.get("/search")
async def search_videos(q: str = Query(..., description="Search query")):
    try:
        videos_search = VideosSearch(q, limit=1)
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

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=1489)

