"""一键把「最终资产 / 项目习惯」同步整理进全局资产库（01_Global_Assets）。

解决痛点：用户在每个项目里反复确认的分镜手法（运镜/光线/情绪/动作）、
确认的画风与负面偏好，原本只留在单个项目里。本模块把它们提取并固化进
【全局】资产库，使后续项目/生成能直接复用、产出更符合个人习惯。

扫描来源：
  - asset_versions(is_final=1) 的分镜提示词（提取运镜/光线/情绪/动作习惯）
  - project_configs.__globals__（画风/色调/光线/氛围/positive/negative）
增量合并策略：
  - 已有同名条目：跳过（不覆盖用户手写资产）
  - 缺失的运镜/光线/情绪/动作：新增条目（来自最终提示词习惯）
  - 项目全局设定：固化为一条可复用 Style 预设
  - negative_prompts.yaml：把项目负面偏好合并进去（去重）
离线优先：默认纯规则提取，无需 LLM；use_llm=True 时调用大模型补描述/提示词。
"""
import os
import re
from collections import Counter

# 各分类关键词词表（与 01_Global_Assets 现有条目对齐，用于从最终提示词提取习惯）
CAMERA_VOCAB = {
    "全景": "full shot, wide shot, establishing shot, 全景",
    "中景": "medium shot, 中景",
    "近景": "close shot, 近景",
    "特写": "close-up, 特写",
    "俯拍": "high angle shot, looking down, overhead, 俯拍",
    "仰拍": "low angle shot, looking up, 仰拍",
    "航拍": "aerial shot, drone shot, 航拍",
    "跟拍": "follow shot, tracking shot, 跟拍",
    "推镜头": "dolly in, push in, 推镜头",
    "拉镜头": "dolly out, pull back, 拉镜头",
    "摇镜头": "pan shot, 摇镜头",
    "旋转环绕": "orbit shot, 360 rotation, 旋转环绕",
}
LIGHTING_VOCAB = {
    "侧逆光": "rim light, backlight, side backlight, 侧逆光",
    "柔光": "soft light, diffuse lighting, 柔光",
    "硬光": "hard light, harsh light, 硬光",
    "自然光": "natural light, daylight, 自然光",
    "霓虹光": "neon light, neon glow, 霓虹光",
    "烛光": "candlelight, warm flicker, 烛光",
    "顶光": "top light, overhead light, 顶光",
}
EMOTION_VOCAB = {
    "紧张": "tense, suspense, 紧张",
    "温馨": "warm, cozy, 温馨",
    "压抑": "oppressive, bleak, 压抑",
    "史诗": "epic, grand, 史诗",
    "孤独": "lonely, solitude, 孤独",
    "愤怒": "angry, rage, 愤怒",
    "浪漫": "romantic, 浪漫",
    "恐惧": "fear, dread, 恐惧",
}
ACTION_VOCAB = {
    "对话": "dialogue, conversation, 对话",
    "追逐": "chase, pursuit, 追逐",
    "打斗": "fight, combat, 打斗",
    "独白": "monologue, 独白",
    "行走": "walking, 行走",
    "回头": "turning back, looking back, 回头",
}


def _scan_keywords(text, vocab):
    """返回 text 中出现过的 vocab 键集合。"""
    if not text:
        return set()
    return {k for k in vocab if k in text}


def collect_signals(project_id=None):
    """汇总最终资产信号（分镜手法计数 + 项目全局设定）。

    - 指定 project_id：直接扫描该项目 07_Prompt 磁盘上的最终分镜 JSON
      （这才是最终分镜提示词的真实落点，未必注册进 asset_versions）。
    - 不指定 project_id：扫描所有 asset_versions(is_final=1, storyboard_prompt)。
    """
    from web.models.asset_models import AssetVersion
    from web.services.prompt_assembly import get_project_globals
    import json

    camera = Counter()
    lighting = Counter()
    emotion = Counter()
    action = Counter()
    neg_tokens = []
    pos_tokens = []
    shot_count = 0

    def _feed(vp, np_):
        nonlocal shot_count
        if not vp:
            return
        shot_count += 1
        for vocab, ctr in (
            (CAMERA_VOCAB, camera), (LIGHTING_VOCAB, lighting),
            (EMOTION_VOCAB, emotion), (ACTION_VOCAB, action),
        ):
            for k in _scan_keywords(vp, vocab):
                ctr[k] += 1
        if np_:
            neg_tokens.append(np_)

    if project_id:
        # 扫描磁盘 07_Prompt 下所有分镜 JSON
        from web.models.database import ProjectModel
        from web.paths import project_subdir
        proj = ProjectModel.query.get(project_id)
        if proj:
            prompt_dir = project_subdir(proj.name, "prompt")
            if os.path.isdir(prompt_dir):
                for fn in sorted(os.listdir(prompt_dir)):
                    if not fn.endswith(".json"):
                        continue
                    try:
                        d = json.load(open(os.path.join(prompt_dir, fn), encoding="utf-8")) or {}
                    except Exception:
                        continue
                    if not isinstance(d, dict):
                        continue
                    _feed(d.get("video_prompt", ""), d.get("negative_prompt", ""))
    else:
        finals = AssetVersion.query.filter_by(is_final=True, asset_type="storyboard_prompt").all()
        for f in finals:
            try:
                d = json.loads(f.content) if isinstance(f.content, str) else (f.content or {})
            except Exception:
                d = {}
            if isinstance(d, dict):
                _feed(d.get("video_prompt", ""), d.get("negative_prompt", ""))

    g = get_project_globals(project_id) if project_id else {}
    if g.get("negative_prompts"):
        neg_tokens.append(g["negative_prompts"])
    if g.get("positive_prompts"):
        pos_tokens.append(g["positive_prompts"])

    return {
        "shot_count": shot_count,
        "camera": camera, "lighting": lighting,
        "emotion": emotion, "action": action,
        "neg_tokens": neg_tokens, "pos_tokens": pos_tokens,
        "globals": g, "project_id": project_id,
    }


def _existing_names(loader, category):
    return {e["name"] for e in loader.list_category(category)}


def build_candidates(signals, loader):
    """根据最终习惯，构造应新增的全局资产候选（跳过库中已有同名）。"""
    candidates = []
    cats = [
        ("Camera", CAMERA_VOCAB, signals["camera"]),
        ("Lighting", LIGHTING_VOCAB, signals["lighting"]),
        ("Emotion", EMOTION_VOCAB, signals["emotion"]),
        ("Action", ACTION_VOCAB, signals["action"]),
    ]
    for category, vocab, counter in cats:
        existing = _existing_names(loader, category)
        for k, cnt in counter.items():
            if k in existing:
                continue
            candidates.append({
                "category": category, "name": k,
                "description": f"从最终分镜习惯提取（出现 {cnt} 次）",
                "prompt": vocab.get(k, k),
                "reason": f"最终分镜中使用了「{k}」{cnt} 次，固化为可复用资产",
            })

    # 项目全局设定 → 一条可复用 Style 预设
    g = signals.get("globals", {})
    style_name = (g.get("art_style") or "").strip()
    if style_name and style_name not in _existing_names(loader, "Style"):
        parts = [g.get("art_style"), g.get("color_palette"), g.get("lighting"),
                 g.get("mood"), g.get("positive_prompts")]
        prompt = "，".join(p for p in parts if p)
        candidates.append({
            "category": "Style", "name": style_name,
            "description": "从项目全局设定固化而来的个人风格预设",
            "prompt": prompt,
            "reason": "项目全局设定（画风/色调/光线/氛围）已确认的风格偏好",
        })
    return candidates


def _merge_tokens(existing, new_tokens):
    """把 new_tokens（可能含逗号分隔）去重合并进 existing 字符串。"""
    seen = [t.strip() for t in re.split(r"[，,；;]", existing or "") if t.strip()]
    for t in new_tokens:
        for piece in re.split(r"[，,；;]", t or ""):
            piece = piece.strip()
            if piece and piece not in seen:
                seen.append(piece)
    return "，".join(seen)


def merge_negative(signals, loader, dry_run=False):
    """把项目负面偏好合并进 negative_prompts.yaml（去重，不丢已有）。"""
    import yaml
    fp = os.path.join(loader.assets_path, "negative_prompts.yaml")
    data = {}
    if os.path.exists(fp):
        try:
            data = yaml.safe_load(open(fp, encoding="utf-8")) or {}
        except Exception:
            data = {}
    data.setdefault("image", "")
    data.setdefault("video", "")
    data.setdefault("character", "")

    updated = []
    for key in ("image", "video", "character"):
        merged = _merge_tokens(data.get(key, ""), signals["neg_tokens"])
        if merged != data.get(key, ""):
            data[key] = merged
            updated.append(key)
    if updated and not dry_run:
        with open(fp, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    return updated


def _enrich_with_llm(candidates, signals):
    """可选：调用大模型为一批量候选补充分描述/提示词（失败则退回规则结果）。"""
    if not candidates:
        return candidates
    try:
        from web.models.database import Provider
        from web.services.llm_client import LLMClient
        provider = Provider.query.filter(Provider.api_key != "").first()
        if not provider:
            return candidates
        client = LLMClient(provider.key, provider.api_key)
        prompt = (
            "你是影视资产顾问。下面是从用户最终确认的分镜中提取、拟新增进全局资产库的条目。"
            "请为每条补充更专业的「提示词」(英文关键词逗号分隔) 与一句话「描述」。\n"
            + "\n".join(
                f'- {c["category"]}/{c["name"]}：原提示词={c["prompt"]}'
                for c in candidates
            )
            + '\n\n返回 JSON：{"items":[{"name":名称,"prompt":提示词,"description":描述}]}'
        )
        out = client.chat_json([{"role": "user", "content": prompt}], max_tokens=2048)
        if isinstance(out, dict) and out.get("items"):
            by_name = {i.get("name"): i for i in out["items"]}
            for c in candidates:
                i = by_name.get(c["name"])
                if i:
                    if i.get("prompt"):
                        c["prompt"] = i["prompt"]
                    if i.get("description"):
                        c["description"] = i["description"]
    except Exception:
        pass
    return candidates


def write_personal_habits(signals, loader, recognized, dry_run=False):
    """把个人习惯画像写入 01_Global_Assets/Personal_Habits.yaml（供后续生成参考）。"""
    data = {
        "描述": "由「最终资产一键同步」生成与维护的个人习惯画像；记录最终分镜中反复出现的"
                "运镜/光线/情绪/动作手法与风格偏好，供后续生成贴合个人习惯。",
        "项目": signals.get("project_id"),
        "分镜样本数": signals["shot_count"],
        "运镜习惯": dict(signals["camera"]),
        "光线习惯": dict(signals["lighting"]),
        "情绪习惯": dict(signals["emotion"]),
        "动作习惯": dict(signals["action"]),
        "已识别(库中已有)": recognized,
        "风格预设": (signals.get("globals", {}) or {}).get("art_style", ""),
    }
    if not dry_run:
        loader.save_asset("", "Personal_Habits.yaml", data)
    return data


def sync_final_assets_to_globals(project_id=None, use_llm=False, dry_run=False):
    """主入口：扫描最终资产 → 提取习惯 → 增量合并进全局资产库。

    返回报告 dict（added / skipped / recognized / negative_updated / scanned_shots）。
    """
    from core.global_asset_loader import GlobalAssetLoader
    from web.config import root_path

    loader = GlobalAssetLoader(root_path())
    signals = collect_signals(project_id)
    candidates = build_candidates(signals, loader)
    if use_llm:
        candidates = _enrich_with_llm(candidates, signals)

    # 已识别的个人习惯（出现在最终分镜且库中已有同名条目）
    recognized = []
    for category, vocab, counter in (
        ("Camera", CAMERA_VOCAB, signals["camera"]),
        ("Lighting", LIGHTING_VOCAB, signals["lighting"]),
        ("Emotion", EMOTION_VOCAB, signals["emotion"]),
        ("Action", ACTION_VOCAB, signals["action"]),
    ):
        existing = _existing_names(loader, category)
        for k, cnt in counter.items():
            if k in existing:
                recognized.append(f"{category}/{k}({cnt}次)")

    report = {
        "scanned_shots": signals["shot_count"],
        "project_id": project_id,
        "added": [],
        "skipped": [],
        "recognized": recognized,
        "negative_updated": [],
    }

    report["negative_updated"] = merge_negative(signals, loader, dry_run=dry_run)
    if not dry_run:
        write_personal_habits(signals, loader, recognized, dry_run=dry_run)
    else:
        report["personal_habits"] = "dry-run 未落盘"

    for c in candidates:
        fname = c["name"] + ".yaml"
        exists = os.path.exists(os.path.join(loader.assets_path, c["category"], fname))
        if exists:
            report["skipped"].append(f'{c["category"]}/{c["name"]}')
            continue
        content = {
            "名称": c["name"],
            "描述": c["description"],
            "提示词": c["prompt"],
            "适用": c.get("reason", ""),
        }
        if dry_run:
            report["added"].append(f'{c["category"]}/{c["name"]} (dry-run)')
        else:
            loader.save_asset(c["category"], fname, content)
            report["added"].append(f'{c["category"]}/{c["name"]}')
    return report
