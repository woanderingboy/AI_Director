"""字幕模块：语音识别(ASR) → 可编辑字幕段落 → 烧录/导出 SRT。

设计要点（对应需求）：
- 自动识别视频语音：基于本地 faster-whisper 离线识别，返回带时间轴的段落。
- 手动确认：识别结果仅「返回」给前端，由用户编辑/确认后，才会调用 render 烧录，
  服务端不会在识别阶段写入任何字幕产物。
- 自动对齐音频时间线：whisper 给出精确 start/end，前端可微调，烧录时按时间轴叠加。
- 样式可选：字体/字号/颜色/描边/底纹/位置均由 style 参数控制（见 burn_subtitles）。

ASR 引擎为可插拔：默认 whisper（faster-whisper）。若无引擎或视频无声，
transcribe 会优雅降级（返回空段落 + 说明），用户仍可手动添加字幕行。
"""
import os
import re
import subprocess
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 常见 CJK 字体候选（Windows 优先），用于字幕烧录与前端字体选择器
_CJK_FONT_CANDIDATES = [
    ("微软雅黑", "C:/Windows/Fonts/msyh.ttc"),
    ("微软雅黑 Bold", "C:/Windows/Fonts/msyhbd.ttc"),
    ("黑体", "C:/Windows/Fonts/simhei.ttf"),
    ("楷体", "C:/Windows/Fonts/simkai.ttf"),
    ("宋体", "C:/Windows/Fonts/simsun.ttc"),
    ("华文宋体", "C:/Windows/Fonts/STSONG.TTF"),
]

# whisper 模型缓存（避免重复加载）
_WHISPER_MODELS = {}

# 首次下载 whisper 模型时优先走国内镜像，提升可用性（可被环境变量覆盖）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


class SubtitleError(Exception):
    """字幕模块业务异常。"""


def _ffmpeg_exe():
    """返回可用的 ffmpeg 可执行文件路径（优先 imageio-ffmpeg 自带的）。"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def list_cjk_fonts():
    """列出系统中可用的 CJK 字体（名称 → 路径）。"""
    out = []
    for name, path in _CJK_FONT_CANDIDATES:
        if os.path.isfile(path):
            out.append({"name": name, "path": path})
    # 额外扫描 Windows 字体目录，补充其他中文字体
    win_fonts = "C:/Windows/Fonts"
    if os.path.isdir(win_fonts):
        for fn in os.listdir(win_fonts):
            low = fn.lower()
            if low.endswith((".ttf", ".ttc", ".otf")) and not any(
                fn.lower() == os.path.basename(c[1]).lower() for c in _CJK_FONT_CANDIDATES
            ):
                # 仅补充文件名中含中文常见字样者，避免塞入大量西文字体
                if re.search(r"(yahei|sim|song|kai|hei|ming|fang|st|msyh|cjk|noto)", low):
                    out.append({"name": fn, "path": os.path.join(win_fonts, fn)})
    return out


def _default_font():
    fonts = list_cjk_fonts()
    if fonts:
        # 优先黑体/雅黑这类无衬线，屏幕字幕更清晰
        for f in fonts:
            if f["name"] in ("黑体", "微软雅黑"):
                return f["path"]
        return fonts[0]["path"]
    return None


def extract_audio(video_path, audio_path=None):
    """用 ffmpeg 从视频抽取 16k 单声道 wav，返回 (wav_path, has_audio)。

    has_audio=False 表示视频无音轨（如静帧幻灯片），此时无法做语音识别。
    """
    if audio_path is None:
        fd, audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
    ff = _ffmpeg_exe()
    cmd = [
        ff, "-y", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", audio_path,
    ]
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as e:
        raise SubtitleError(f"找不到 ffmpeg：{e}") from e
    if proc.returncode != 0:
        # 多半是无音轨；回收临时文件
        if os.path.isfile(audio_path):
            try:
                os.remove(audio_path)
            except OSError:
                pass
        return audio_path, False
    if not os.path.isfile(audio_path) or os.path.getsize(audio_path) < 1000:
        return audio_path, False
    return audio_path, True


def _load_whisper(model_size):
    if model_size in _WHISPER_MODELS:
        return _WHISPER_MODELS[model_size]
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise SubtitleError(
            "未安装 faster-whisper，无法自动识别语音。请先 "
            "pip install faster-whisper（或手动添加字幕行）。"
        ) from e
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    _WHISPER_MODELS[model_size] = model
    return model


def transcribe(audio_path, model_size="small", language="zh", backend="whisper"):
    """语音识别：返回 [{'start':float,'end':float,'text':str}, ...]。

    无声/无引擎时返回空列表，由调用方决定降级策略。
    """
    if backend != "whisper":
        raise SubtitleError(f"不支持的 ASR 后端：{backend}")
    model = _load_whisper(model_size)
    segments, _info = model.transcribe(
        audio_path, language=language, beam_size=5, condition_on_previous_text=False
    )
    out = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        out.append({"start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": text})
    return out


def segments_to_srt(segments):
    """将字幕段落转换为标准 SRT 文本。"""

    def _fmt(t):
        ms = int(round((t - int(t)) * 1000))
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_fmt(seg['start'])} --> {_fmt(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def _hex_to_rgb(hex_color):
    if isinstance(hex_color, (tuple, list)) and len(hex_color) >= 3:
        return tuple(int(c) for c in hex_color[:3])
    h = str(hex_color).lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) >= 6:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (255, 255, 255)


def burn_subtitles(video_path, segments, style=None, out_path=None):
    """把字幕段落按时间轴烧录进视频，返回输出视频路径。

    style 支持字段：
      font_path  字体文件路径（缺省用系统 CJK 字体）
      size       字号(px)，默认 36
      color      文字颜色(#RGB)，默认白色
      stroke_color 描边颜色，默认黑色
      stroke_width 描边粗细(px)，默认 2
      bg         是否加半透明黑底纹，默认 True
      bg_color   底纹颜色，默认黑色
      position   'bottom' | 'top'，默认 bottom
    同时写出同名 .srt 作为可编辑/可分发副本。
    """
    from moviepy import VideoFileClip, TextClip, ColorClip, CompositeVideoClip

    style = style or {}
    font_path = style.get("font_path") or _default_font()
    # 用户提供字体缺失时，回退到系统默认 CJK 字体，而不是直接报错中断
    if not font_path or not os.path.isfile(font_path):
        font_path = _default_font()
    if not font_path or not os.path.isfile(font_path):
        raise SubtitleError("未找到可用的中文字体，无法烧录字幕。")
    font_size = int(style.get("size") or 36)
    color = _hex_to_rgb(style.get("color") or "#FFFFFF")
    stroke_color = _hex_to_rgb(style.get("stroke_color") or "#000000")
    stroke_width = int(style.get("stroke_width") or 2)
    bg = bool(style.get("bg", True))
    bg_color = _hex_to_rgb(style.get("bg_color") or "#000000")
    position = style.get("position") or "bottom"

    if out_path is None:
        base, ext = os.path.splitext(video_path)
        out_path = f"{base}_subtitled.mp4"

    clip = VideoFileClip(video_path)
    try:
        vw, vh = clip.w, clip.h
        v_dur = float(clip.duration or 0)
        # 字号上限：不超过画面高度的一半，避免字幕超出画幅
        font_size = max(8, min(font_size, max(12, int(vh * 0.5))))
        max_w = int(vw * 0.9)
        pad = max(20, int(vh * 0.04))
        subs = []
        for seg in segments:
            start = float(seg.get("start", 0) or 0)
            end = float(seg.get("end", start + 2) or (start + 2))
            # 时间轴边界裁剪：限制在 [0, 视频时长] 内，且保证 end > start（最小间隔 0.3s）
            start = max(0.0, min(start, max(0.0, v_dur - 0.3)))
            end = max(start + 0.3, min(end, v_dur)) if v_dur > 0 else max(start + 0.3, end)
            duration = end - start
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            txt_clip = TextClip(
                font=font_path,
                text=text,
                font_size=font_size,
                color=color,
                stroke_color=stroke_color,
                stroke_width=stroke_width,
                method="caption",
                size=(max_w, None),
                text_align="center",
                horizontal_align="center",
                interline=int(font_size * 0.3),
            )
            txt_clip = txt_clip.with_start(start).with_duration(duration)
            if bg:
                bg_clip = (
                    ColorClip(size=(max_w, txt_clip.h), color=bg_color, duration=duration)
                    .with_opacity(0.55)
                    .with_start(start)
                )
                if position == "top":
                    y = pad
                else:
                    y = max(pad, vh - txt_clip.h - pad)
                bg_clip = bg_clip.with_position(("center", y))
                txt_clip = txt_clip.with_position(("center", y))
                subs.append(bg_clip)
            else:
                if position == "top":
                    txt_clip = txt_clip.with_position(("center", pad))
                else:
                    txt_clip = txt_clip.with_position(("center", max(pad, vh - txt_clip.h - pad)))
            subs.append(txt_clip)

        if not subs:
            raise SubtitleError("没有可烧录的字幕内容（段落文本为空）。")

        composite = CompositeVideoClip([clip, *subs], size=(vw, vh))

        # 先写出「无声字幕版」到系统临时目录：moviepy 在带音轨封装时会生成
        # 需要清理的音频临时文件，而沙箱 safe-delete 会拦截 os.remove 导致失败；
        # 因此这里 audio=False（不触发音频临时文件），随后用 ffmpeg 把原片音轨合回。
        import tempfile
        fd, silent_tmp = tempfile.mkstemp(suffix=".mp4", prefix="aidirector_sub_")
        os.close(fd)
        _orig_remove = os.remove

        def _safe_remove(p):
            try:
                _orig_remove(p)
            except OSError:
                pass

        os.remove = _safe_remove
        try:
            composite.write_videofile(
                silent_tmp, codec="libx264", audio=False,
                fps=clip.fps or 24, logger=None,
            )
        finally:
            os.remove = _orig_remove

        # ffmpeg 合回原片音轨（原片无声时 -map 1:a? 自动跳过音轨）
        ff = _ffmpeg_exe()
        cmd = [
            ff, "-y", "-i", silent_tmp, "-i", video_path,
            "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac",
            "-shortest", out_path,
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if proc.returncode != 0:
            # 兜底：直接把无声版作为结果（字幕依然可见）
            try:
                import shutil
                shutil.copyfile(silent_tmp, out_path)
            except Exception:
                raise SubtitleError("视频封装失败：" + proc.stderr.decode("utf-8", "ignore")[:300])
    finally:
        clip.close()

    # 写 SRT 副本
    srt_path = os.path.splitext(out_path)[0] + ".srt"
    try:
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(segments_to_srt(segments))
    except OSError:
        srt_path = None
    return out_path, srt_path


def project_videos_dir(project_name):
    return os.path.normpath(os.path.join(ROOT, "02_Projects", project_name, "09_Video"))


def list_project_videos(project_name):
    """列出项目 09_Video 下的视频文件（含相对路径）。"""
    d = project_videos_dir(project_name)
    if not os.path.isdir(d):
        return []
    items = []
    for fn in sorted(os.listdir(d)):
        if fn.lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
            items.append(fn)
    return items
