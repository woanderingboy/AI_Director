"""分镜画布 API - 把提示词、静帧、匹配全局资产组装成统一视图

让前端可以在一张「卡片」里同时看到：
  · 该分镜的电影级提示词（video_prompt / negative_prompt / 镜头 / 灯光 / 氛围）
  · 由 Seedream 真实生成的静帧（08_Image 下与提示词同名图片）
  · 自动匹配到的全局资产库条目（机位/光线/风格/情绪…），作为「视觉参考」来源
"""
import os
import json
import yaml

from flask import Blueprint, jsonify, current_app

bp = Blueprint("storyboard", __name__)

# 全局资产分类 → 前端配色（与 index.html 的 CSS 变量一一对应）
CATEGORY_COLORS = {
    "Camera": "blue", "Lighting": "amber", "Style": "purple",
    "Emotion": "rose", "Action": "green", "Transition": "cyan",
}
CATEGORY_ICONS = {
    "Camera": "📹", "Lighting": "💡", "Style": "🎨",
    "Emotion": "🎭", "Action": "🏃", "Transition": "🔀",
}
ASSET_DIRS = ["Camera", "Lighting", "Style", "Emotion", "Action", "Transition"]
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _load_global_assets(root_path):
    """读取全局资产库，返回扁平列表 [{category, name, description, keywords, filename}]"""
    assets = []
    gpath = os.path.join(root_path, "01_Global_Assets")
    for cat in ASSET_DIRS:
        cdir = os.path.join(gpath, cat)
        if not os.path.isdir(cdir):
            continue
        for f in sorted(os.listdir(cdir)):
            if not f.endswith((".yaml", ".yml")):
                continue
            try:
                with open(os.path.join(cdir, f), "r", encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
            except Exception:
                continue
            name = data.get("名称") or os.path.splitext(f)[0]
            desc = data.get("描述") or data.get("描述说明") or ""
            kws = []
            if name:
                kws.append(name)
            kwp = data.get("提示词") or ""
            if kwp:
                kws.extend([k.strip() for k in str(kwp).replace("，", ",").split(",") if k.strip()])
            kws.append(os.path.splitext(f)[0])  # 文件名本身也作为匹配关键词
            assets.append({
                "category": cat,
                "name": name,
                "description": desc,
                "keywords": kws,
                "filename": f,
            })
    return assets


def _match_assets(video_prompt, global_assets):
    """把一条分镜提示词与全局资产库做关键词匹配，返回命中的资产（去重）"""
    matched = []
    seen = set()
    for a in global_assets:
        for kw in a["keywords"]:
            if len(kw) >= 2 and kw in video_prompt:
                key = (a["category"], a["name"])
                if key in seen:
                    continue
                seen.add(key)
                matched.append({
                    "category": a["category"],
                    "color": CATEGORY_COLORS.get(a["category"], "purple"),
                    "icon": CATEGORY_ICONS.get(a["category"], "📄"),
                    "name": a["name"],
                    "description": a["description"],
                    "matched_keyword": kw,
                })
                break
    return matched


@bp.route("/<int:project_id>", methods=["GET"])
def get_storyboard(project_id):
    from web.models.database import ProjectModel
    proj = ProjectModel.query.get_or_404(project_id)
    project_name = proj.name
    root_path = current_app.config["ROOT_PATH"]
    proj_dir = os.path.join(root_path, "02_Projects", project_name)
    prompt_dir = os.path.join(proj_dir, "07_Prompt")
    image_dir = os.path.join(proj_dir, "08_Image")
    global_assets = _load_global_assets(root_path)

    shots = []
    if os.path.isdir(prompt_dir):
        for pf in sorted(os.listdir(prompt_dir)):
            if not pf.endswith(".json"):
                continue
            try:
                with open(os.path.join(prompt_dir, pf), "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            stem = os.path.splitext(pf)[0]
            vp = data.get("video_prompt", "")

            # 匹配静帧：优先同名图片，其次文件名前缀匹配
            image = None
            if os.path.isdir(image_dir):
                if os.path.exists(os.path.join(image_dir, stem + ".png")):
                    image = stem + ".png"
                else:
                    for ext in IMAGE_EXTS:
                        if os.path.exists(os.path.join(image_dir, stem + ext)):
                            image = stem + ext
                            break
                if image is None:
                    for f in os.listdir(image_dir):
                        if f.lower().startswith(stem) and f.lower().endswith(IMAGE_EXTS):
                            image = f
                            break

            # 从文件名抽取镜头号 Sxx
            import re
            m = re.search(r"_S(\d+)", stem)
            shot_label = f"S{m.group(1)}" if m else f"#{data.get('shot_id', len(shots) + 1)}"

            shots.append({
                "shot_file": pf,
                "shot_label": shot_label,
                "shot_id": data.get("shot_id"),
                "scene_id": data.get("scene_id"),
                "video_prompt": vp,
                "negative_prompt": data.get("negative_prompt", ""),
                "camera": data.get("camera", ""),
                "lighting": data.get("lighting", ""),
                "duration": data.get("duration", ""),
                "mood": data.get("mood", ""),
                "image": image,
                "characters": data.get("characters", []),
                "locked_characters": data.get("locked_characters", []),
                "location": data.get("location", ""),
                "assets": _match_assets(vp, global_assets),
            })

    return jsonify({
        "project_name": project_name,
        "project_id": project_id,
        "shots": shots,
        "shot_count": len(shots),
        "with_image": sum(1 for s in shots if s["image"]),
    })
