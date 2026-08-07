"""生成带中文语音的测试视频，用于验证字幕模块的 ASR→烧录链路。"""
import asyncio, os
import edge_tts
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

ROOT = "D:/AI_Director"
PROJ = "离线演示项目"
IMG_DIR = os.path.join(ROOT, "02_Projects", PROJ, "08_Image")
VID_DIR = os.path.join(ROOT, "02_Projects", PROJ, "09_Video")
TMP_MP3 = os.path.join(VID_DIR, "_tts_tmp.mp3")
OUT = os.path.join(VID_DIR, "字幕测试语音.mp4")

TEXT = ("凌晨两点，地下停车场空无一人。陈默握紧手中的手电，缓缓逼近那辆黑色轿车。"
        "突然，车后座传来一声闷响。他屏住呼吸，轻轻拉开车门。"
        "黑暗中，一双惊恐的眼睛正盯着他。这一刻，所有的训练都派上了用场。")

async def tts():
    comm = edge_tts.Communicate(TEXT, voice="zh-CN-XiaoxiaoNeural")
    await comm.save(TMP_MP3)
    print("tts saved", os.path.getsize(TMP_MP3), "bytes")

asyncio.run(tts())

imgs = [os.path.join(IMG_DIR, f"停车场重逢_prompt_S0{i}.png") for i in range(1, 6)]
audio = AudioFileClip(TMP_MP3)
total = audio.duration
dur = total / len(imgs)
clips = [ImageClip(p).with_duration(dur) for p in imgs]
video = concatenate_videoclips(clips, method="compose").with_audio(audio)
video.write_videofile(OUT, codec="libx264", audio_codec="aac", fps=24, logger=None)
print("video written", OUT, os.path.getsize(OUT), "bytes; duration≈", round(total, 2))
os.remove(TMP_MP3)
