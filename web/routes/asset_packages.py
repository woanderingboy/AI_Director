"""素材打包 API - 从分镜提取需求，匹配资产库，打包导出"""
import os
import json
import shutil
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from web.models.database import db
from web.models.asset_models import AssetVersion, AssetPackage

bp = Blueprint("asset_packages", __name__)


def _parse_prompt_requirements(prompt_text):
    """从提示词中提取资产需求关键词"""
    # 简单的关键词提取（实际可接 LLM 做更精确的提取）
    categories = {
        "角色": [], "场景": [], "道具": [], "光线": [], "镜头": [], "风格": [], "情绪": [],
    }
    keywords_map = {
        "角色": ["人物", "角色", "青年", "少女", "男人", "女人", "少年", "老人", "战士", "魔法师", "主角", "反派"],
        "场景": ["城市", "废墟", "森林", "宫殿", "房间", "街道", "天空", "海洋", "山脉", "战场", "学校", "医院"],
        "道具": ["剑", "武器", "法杖", "戒指", "项链", "书", "信", "钥匙", "药水", "手机"],
        "光线": ["侧逆光", "顶光", "柔光", "硬光", "逆光", "黄昏", "月光", "烛光", "霓虹"],
        "镜头": ["全景", "中景", "近景", "特写", "俯拍", "仰拍", "跟拍", "航拍"],
        "风格": ["暗调", "冷色调", "暖色调", "高饱和", "低饱和", "电影感", "动漫风", "写实"],
        "情绪": ["压抑", "孤独", "温馨", "紧张", "悲伤", "欢乐", "恐惧", "浪漫", "壮烈"],
    }

    for cat, kws in keywords_map.items():
        for kw in kws:
            if kw in prompt_text:
                categories[cat].append(kw)

    return categories


def _match_asset_files(project_name, requirements):
    """在资产目录中匹配已有素材"""
    root_path = current_app.config["ROOT_PATH"]
    matched = []
    missing = []

    # 全局资产匹配
    global_path = os.path.join(root_path, "01_Global_Assets")
    for cat, keywords in requirements.items():
        if not keywords:
            continue
        cat_map = {
            "光线": "Lighting", "镜头": "Camera", "风格": "Style",
            "情绪": "Emotion", "道具": "Template",
        }
        dir_name = cat_map.get(cat)
        if dir_name:
            cat_path = os.path.join(global_path, dir_name)
            if os.path.isdir(cat_path):
                for f in os.listdir(cat_path):
                    for kw in keywords:
                        if kw in f:
                            matched.append({
                                "source": "global", "category": dir_name,
                                "filename": f, "keyword": kw,
                                "path": os.path.join(cat_path, f),
                            })

    # 项目资产匹配
    if project_name:
        proj_path = os.path.join(root_path, "02_Projects", project_name)
        for sub, cat_name in [("08_Image", "图片"), ("09_Video", "视频")]:
            dir_path = os.path.join(proj_path, sub)
            if os.path.isdir(dir_path):
                for f in os.listdir(dir_path):
                    matched.append({
                        "source": "project", "category": cat_name,
                        "filename": f, "keyword": "",
                        "path": os.path.join(dir_path, f),
                    })

    # 检查缺失的资产（有关键词但没匹配到文件的）
    for cat, keywords in requirements.items():
        for kw in keywords:
            found = any(kw in m["keyword"] or kw in m["filename"] for m in matched)
            if not found:
                missing.append({"category": cat, "keyword": kw})

    return matched, missing


def _naming_convention(asset_type, name, keywords, version="final"):
    """生成规范文件名"""
    # 格式: {类型}_{名称}_{关键词}_{版本}.{ext}
    safe_name = name.replace(" ", "_").replace("/", "-")[:30]
    safe_kw = "_".join(keywords[:3]) if keywords else ""
    parts = [asset_type, safe_name]
    if safe_kw:
        parts.append(safe_kw)
    parts.append(version)
    return "_".join(parts)


@bp.route("/<int:project_id>/analyze", methods=["POST"])
def analyze_requirements(project_id):
    """分析分镜提示词，提取资产需求"""
    data = request.get_json()
    prompt_text = data.get("prompt_text", "")

    if not prompt_text:
        # 尝试从项目分镜中获取
        from web.models.novel_models import NovelScene
        scenes = NovelScene.query.filter_by(project_id=project_id).all()
        prompt_text = " ".join([s.summary or "" for s in scenes])

    requirements = _parse_prompt_requirements(prompt_text)

    project_name = None
    from web.models.database import ProjectModel
    proj = ProjectModel.query.get(project_id)
    if proj:
        project_name = proj.name

    matched, missing = _match_asset_files(project_name, requirements)

    return jsonify({
        "requirements": requirements,
        "matched": matched,
        "missing": missing,
        "matched_count": len(matched),
        "missing_count": len(missing),
    })


@bp.route("/<int:project_id>/create", methods=["POST"])
def create_package(project_id):
    """创建素材打包"""
    data = request.get_json()
    name = data.get("name", f"素材包_{datetime.now().strftime('%m%d_%H%M')}")
    prompt_text = data.get("prompt_text", "")

    if not prompt_text:
        from web.models.novel_models import NovelScene
        scenes = NovelScene.query.filter_by(project_id=project_id).all()
        prompt_text = " ".join([s.summary or "" for s in scenes])

    requirements = _parse_prompt_requirements(prompt_text)

    project_name = None
    from web.models.database import ProjectModel
    proj = ProjectModel.query.get(project_id)
    if proj:
        project_name = proj.name

    matched, missing = _match_asset_files(project_name, requirements)

    pkg = AssetPackage(
        project_id=project_id,
        name=name,
        description=data.get("description", ""),
        required_assets=json.dumps(requirements, ensure_ascii=False),
        matched_assets=json.dumps(matched, ensure_ascii=False, default=str),
        missing_assets=json.dumps(missing, ensure_ascii=False),
        status="ready" if not missing else "draft",
    )
    db.session.add(pkg)
    db.session.commit()
    return jsonify(pkg.to_dict()), 201


@bp.route("/<int:project_id>/packages", methods=["GET"])
def list_packages(project_id):
    """列出项目的所有打包"""
    packages = AssetPackage.query.filter_by(project_id=project_id).order_by(AssetPackage.created_time.desc()).all()
    return jsonify([p.to_dict() for p in packages])


@bp.route("/packages/<int:pkg_id>", methods=["GET"])
def get_package(pkg_id):
    """获取打包详情"""
    pkg = AssetPackage.query.get_or_404(pkg_id)
    return jsonify(pkg.to_dict())


@bp.route("/packages/<int:pkg_id>", methods=["DELETE"])
def delete_package(pkg_id):
    """删除打包"""
    pkg = AssetPackage.query.get_or_404(pkg_id)
    db.session.delete(pkg)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/packages/<int:pkg_id>/export", methods=["POST"])
def export_package(pkg_id):
    """导出素材包到指定目录"""
    pkg = AssetPackage.query.get_or_404(pkg_id)
    root_path = current_app.config["ROOT_PATH"]
    data = request.get_json() or {}
    export_dir = data.get("export_dir", os.path.join(root_path, "04_Output", f"package_{pkg.id}"))

    matched = json.loads(pkg.matched_assets) if pkg.matched_assets else []
    exported = []
    errors = []

    # 检查是否有内容可导出
    if not matched:
        return jsonify({
            "ok": False,
            "error": "没有匹配的资产可导出。请先将资产图放入 02_Projects/{项目名}/08_Image/ 目录，或在「资产管理」中导入素材。",
            "exported_count": 0,
            "exported": [],
            "errors": [],
        }), 400

    os.makedirs(export_dir, exist_ok=True)

    for asset in matched:
        src = asset.get("path", "")
        if not os.path.exists(src):
            errors.append(f"文件不存在: {src}")
            continue
        # 使用规范命名
        ext = os.path.splitext(src)[1]
        category = asset.get("category", "unknown")
        keyword = asset.get("keyword", "")
        safe_name = _naming_convention(category, os.path.splitext(asset.get("filename", ""))[0], [keyword] if keyword else [])
        dst = os.path.join(export_dir, f"{safe_name}{ext}")
        try:
            shutil.copy2(src, dst)
            exported.append(dst)
        except Exception as e:
            errors.append(f"复制失败 {src}: {e}")

    # 生成 index.json 汇总
    index_data = {
        "project": project_name or "unknown",
        "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "shots": [],
        "assets": [],
    }

    # 读取提示词文件
    prompt_dir = os.path.join(root_path, "02_Projects", project_name or "", "07_Prompt")
    if os.path.isdir(prompt_dir):
        for pf in sorted(os.listdir(prompt_dir)):
            if pf.endswith(".json"):
                try:
                    with open(os.path.join(prompt_dir, pf), "r", encoding="utf-8") as f:
                        pdata = json.load(f)
                    index_data["shots"].append({
                        "file": pf,
                        "video_prompt": pdata.get("video_prompt", ""),
                        "negative_prompt": pdata.get("negative_prompt", ""),
                        "camera": pdata.get("camera", ""),
                        "duration": pdata.get("duration", ""),
                        "matched_asset": None,
                    })
                except Exception:
                    pass

    # 匹配资产图
    for asset in matched:
        asset_info = {
            "filename": asset.get("filename", ""),
            "category": asset.get("category", ""),
            "keyword": asset.get("keyword", ""),
            "source": asset.get("source", ""),
        }
        index_data["assets"].append(asset_info)
        # 尝试关联到对应的 shot
        for shot in index_data["shots"]:
            if asset.get("keyword", "") and asset["keyword"] in shot.get("video_prompt", ""):
                shot["matched_asset"] = asset.get("filename", "")

    # 写入 index.json
    index_path = os.path.join(export_dir, "index.json")
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    exported.append(index_path)

    # 复制提示词文件到导出目录
    if os.path.isdir(prompt_dir):
        prompt_export = os.path.join(export_dir, "prompts")
        os.makedirs(prompt_export, exist_ok=True)
        for pf in os.listdir(prompt_dir):
            if pf.endswith(".json"):
                src = os.path.join(prompt_dir, pf)
                dst = os.path.join(prompt_export, pf)
                shutil.copy2(src, dst)
                exported.append(dst)

    pkg.export_path = export_dir
    pkg.status = "packed"
    db.session.commit()

    return jsonify({
        "ok": True,
        "export_dir": export_dir,
        "exported_count": len(exported),
        "exported": exported,
        "errors": errors,
        "index": index_data,
    })


@bp.route("/naming-preview", methods=["POST"])
def naming_preview():
    """预览文件命名"""
    data = request.get_json()
    result = _naming_convention(
        data.get("asset_type", "asset"),
        data.get("name", "unnamed"),
        data.get("keywords", []),
        data.get("version", "final"),
    )
    return jsonify({"filename": result})
