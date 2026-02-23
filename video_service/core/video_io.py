import os
import cv2
import yt_dlp
from PIL import Image
from video_service.core.utils import logger

def get_stream_url(video_url):
    if os.path.exists(video_url): return video_url
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl: return ydl.extract_info(video_url, download=False).get('url', video_url)
    except: return video_url

def extract_frames_for_pipeline(url):
    cap = cv2.VideoCapture(get_stream_url(url))
    frames = []
    if not cap.isOpened():
        return frames, cap
    
    fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total <= 0 or fps <= 0:
        return frames, cap

    for t in range(int(max(0, (total/fps)-3)*fps), total, max(1, int(total/6))):
        cap.set(cv2.CAP_PROP_POS_FRAMES, t)
        ret, fr = cap.read()
        if ret: 
            frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/fps, "type": "tail"})
    
    return frames, cap

def extract_frames_for_agent(url):
    cap = cv2.VideoCapture(get_stream_url(url))
    frames = []
    if not cap.isOpened():
        return frames, cap
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or total <= 0:
        return frames, cap

    for t in range(0, total, int(fps*2)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, t)
        ret, fr = cap.read()
        if ret: 
            frames.append({"image": Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)), "ocr_image": fr, "time": t/fps, "type": "scene"})
    
    return frames, cap

def resolve_urls(src, urls, fldr):
    if src == "Web URLs":
        return [u.strip() for u in urls.split("\n") if u.strip()]
    elif os.path.isdir(fldr):
        return [os.path.join(fldr, f) for f in os.listdir(fldr) if f.lower().endswith(('.mp4', '.mov'))]
    return []
