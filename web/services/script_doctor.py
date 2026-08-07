"""剧本体检（Script Doctor）—— 生成前的结构 / 人物压力 / 节奏诊断。

纯函数式分析，输入一组已解析的剧本 JSON 与角色库，输出结构化体检报告。
不调用任何 LLM，秒级返回，适合作为「生成前」的廉价预检；
深度评语由路由层的 AI 端点另行提供。
"""
from __future__ import annotations

import re
from collections import defaultdict


# ───────────────────────── 强度词典 ─────────────────────────
# 情绪强度（取角色中出现的最高档）
EMO_HIGH = ["恐惧", "惊恐", "紧张", "粗暴", "痛苦", "惊愕", "凌厉", "愤怒", "绝望",
            "慌乱", "暴怒", "狂怒", "崩溃", "濒死", "危机", "对峙", "厮杀", "歇斯底里"]
EMO_MED = ["警觉", "冷静", "果断", "不安", "焦虑", "疑惑", "悲伤", "担忧", "惊讶",
           "沉默", "隐忍", "压抑", "戒备", "狠厉"]
EMO_LOW = ["沉静", "温和", "平静", "舒缓", "宿命", "温柔", "安详", "宁静", "释然", "怅然"]

# 动作 / 冲突强度（统计场景描述里的命中次数）
ACT_HIGH = ["击倒", "踢飞", "制服", "挣扎", "搏斗", "厮杀", "开枪", "挥拳", "格挡",
            "反关节", "踢", "打", "逃", "追", "袭击", "擒", "扭", "撞", "坠", "爆",
            "血", "杀", "扑", "冲", "闪", "刺", "斩", "砸", "掐", "勒"]
ACT_MED = ["巡逻", "潜行", "伸手", "转身", "靠近", "抬头", "低头", "握", "指", "推",
           "拉", "跑", "走", "站", "坐", "挡", "擒拿", "闪避"]
# 被动标记（角色被施加动作，缺乏主动性）
ACT_PASSIVE = ["被击倒", "被踢飞", "被反关节", "被控制", "被擒", "被抓", "被绑",
               "被勒", "被掐", "被按倒", "被袭击", "被追", "被逃", "被制服"]

# 氛围强度
MOOD_HIGH = ["紧张", "悬疑", "凌厉", "激烈", "危机", "高潮", "冲突", "压抑", "慌乱", "惊险"]
MOOD_LOW = ["宿命", "救赎", "温柔", "平静", "舒缓", "温馨", "感伤", "宁静", "释然", "唯美"]


def _has_any(text, words):
    return any(w in text for w in words)


def _emo_score(text):
    if _has_any(text, EMO_HIGH):
        return 9.0
    if _has_any(text, EMO_MED):
        return 5.5
    if _has_any(text, EMO_LOW):
        return 3.0
    return 4.0


def _act_score(desc):
    hits = sum(desc.count(w) for w in ACT_HIGH)
    if hits >= 3:
        return 9.0
    if hits >= 1:
        return 6.0
    if _has_any(desc, ACT_MED):
        return 4.0
    return 2.0


def scene_intensity(scene):
    """把单个场景映射为 0-10 的戏剧强度。"""
    emo_text = " ".join(str(c.get("emotion", "")) for c in scene.get("characters", []) if isinstance(c, dict))
    desc = scene.get("description", "") or ""
    mood = scene.get("mood", "") or ""
    chars = scene.get("characters", []) or []

    emo = _emo_score(emo_text + " " + mood)
    act = _act_score(desc)
    mood_boost = 1.5 if _has_any(mood, MOOD_HIGH) else (0.0 if _has_any(mood, MOOD_LOW) else 0.6)
    char_factor = min(len(chars), 6) / 6.0 * 1.5

    intensity = emo * 0.45 + act * 0.40 + char_factor + mood_boost
    return round(max(0.0, min(10.0, intensity)), 1)


def _collect_scenes(scripts):
    """汇总所有剧本的「场景」(优先) 或退化为 shots。"""
    scenes = []
    for sc in scripts:
        sc_scenes = sc.get("scenes") or []
        if sc_scenes:
            scenes.extend(sc_scenes)
        else:
            # 退化：用 shots 当场景
            for sh in sc.get("shots", []):
                scenes.append({
                    "scene_id": sh.get("shot_id"),
                    "location": sh.get("location", ""),
                    "time": sh.get("time", ""),
                    "characters": sh.get("characters", []),
                    "dialogue": sh.get("dialogue", []),
                    "camera": sh.get("camera", ""),
                    "mood": sh.get("mood", ""),
                    "description": sh.get("description", ""),
                    "estimated_seconds": sh.get("duration") or 0,
                })
    return scenes


def _char_name(c):
    if isinstance(c, dict):
        return (c.get("name") or "").strip()
    if isinstance(c, str):
        return c.strip()
    return ""


def analyze_scripts(scripts, characters_lib=None):
    """核心体检。

    scripts:        list[dict]  已解析的剧本 JSON
    characters_lib: list[dict]  角色库记录（含 name/role/motivation/arc/appearance）
    返回结构化报告 dict。
    """
    characters_lib = characters_lib or []
    lib_by_name = {c.get("name", "").strip(): c for c in characters_lib if c.get("name")}

    scenes = _collect_scenes(scripts)
    total = len(scenes)
    report = {
        "script_count": len(scripts),
        "scene_count": total,
        "total_runtime": 0,
        "categories": {},
        "issues": [],
        "tension_curve": [],
        "overall_score": 0,
        "overall_grade": "—",
    }
    if total == 0:
        report["issues"].append({
            "severity": "error", "category": "结构",
            "text": "未检测到任何剧本场景，请先运行「剧本生成」。",
            "fix": "进入「剧本生成」阶段生成结构化剧本后再做体检。",
        })
        return report

    # ── 基础统计 ──
    runtimes = [float(s.get("estimated_seconds") or s.get("duration") or 0) for s in scenes]
    report["total_runtime"] = round(sum(runtimes), 1)
    avg_len = (sum(runtimes) / total) if runtimes else 0

    # ── 角色出场统计 ──
    appearances = defaultdict(int)
    char_emotions = defaultdict(set)
    char_actions = defaultdict(list)
    char_has_active = defaultdict(bool)
    for s in scenes:
        seen = set()
        for c in s.get("characters", []) or []:
            n = _char_name(c)
            if not n or n in seen:
                continue
            seen.add(n)
            appearances[n] += 1
            if isinstance(c, dict):
                if c.get("emotion"):
                    char_emotions[n].add(c["emotion"])
                act = str(c.get("action", ""))
                char_actions[n].append(act)
                # 主动标记：不含「被」且无被动词，且含有动作
                if "被" not in act and any(w in act for w in ACT_HIGH + ACT_MED):
                    char_has_active[n] = True
    total_app = max(1, sum(appearances.values()))

    # ── 张力曲线 + 三幕 ──
    curve = []
    for i, s in enumerate(scenes):
        it = scene_intensity(s)
        act_band = "一幕" if i < total / 3 else ("二幕" if i < total * 2 / 3 else "三幕")
        curve.append({
            "index": i + 1,
            "label": f"场{i + 1}",
            "location": (s.get("location") or "").strip(),
            "intensity": it,
            "act": act_band,
        })
    report["tension_curve"] = curve

    intensities = [c["intensity"] for c in curve]
    climax_idx = max(range(total), key=lambda k: intensities[k])
    climax_val = intensities[climax_idx]
    end_val = intensities[-1]

    # ══════════════ 结构诊断 ══════════════
    struct_issues = []
    struct_score = 100
    # 开篇钩子
    if intensities[0] < 3:
        struct_issues.append({"severity": "warning", "text": "开篇强度偏低，缺少能抓住观众的「钩子」场景。",
                              "fix": "用更强的冲突、悬念或反差开场（如异常事件/人物处境突变）。"})
    # 高潮位置
    if climax_idx < total * 0.66:
        struct_issues.append({"severity": "warning",
                              "text": f"高潮出现在第 {climax_idx + 1} 场（偏前），而非接近结尾，结构张力释放过早。",
                              "fix": "把最大冲突/转折挪到后 1/3，让压力持续累积到结尾前。"})
        struct_score -= 10
    # 收尾释放
    if end_val >= climax_val - 0.5 and total >= 3:
        struct_issues.append({"severity": "warning",
                              "text": "结尾强度未明显低于高潮，缺少「释放/余韵」，观众难以落幕。",
                              "fix": "结尾用情绪反差、安静或代价呈现，让强度回落。"})
        struct_score -= 8
    # 拖沓（连续 3+ 场强度方差极小）
    flat = 0
    for i in range(total - 2):
        seg = intensities[i:i + 3]
        if max(seg) - min(seg) < 1.2:
            flat += 1
    if flat >= 1 and total >= 5:
        struct_issues.append({"severity": "warning",
                              "text": f"检测到 {flat} 处连续平场（强度几乎无起伏），节奏易显拖沓。",
                              "fix": "在平场间插入转折、新信息或强度落差，打破单调。"})
        struct_score -= 8 * min(flat, 2)
    # 整体递增性
    first_third = intensities[: max(1, total // 3)]
    last_third = intensities[-max(1, total // 3):]
    if avg(first_third) > avg(last_third) + 1.5:
        struct_issues.append({"severity": "warning", "text": "强度整体前高后低，缺少「 escalating」的累积感。",
                              "fix": "重新排布事件，使压力/赌注随进程上升。"})
        struct_score -= 8
    if not struct_issues:
        struct_issues.append({"severity": "ok", "text": "三幕张力分布基本合理，开篇有钩子、高潮位置与收尾释放未见明显问题。", "fix": ""})
    struct_score = max(0, min(100, struct_score))
    report["categories"]["structure"] = {
        "score": struct_score,
        "label": "结构",
        "metrics": {
            "场景数": total,
            "总时长(秒)": report["total_runtime"],
            "高潮场": f"第{climax_idx + 1}场 (强度{climax_val})",
            "场均时长(秒)": round(avg_len, 1),
        },
    }

    # ══════════════ 人物压力诊断 ══════════════
    char_issues = []
    char_score = 100
    named = [n for n in appearances if not re.fullmatch(r"群演\d*|路人[甲乙丙丁]?", n)]
    # 失衡
    top_name, top_cnt = max(appearances.items(), key=lambda kv: kv[1])
    top_share = top_cnt / total_app
    if top_share > 0.55 and total >= 4:
        char_issues.append({"severity": "warning",
                            "text": f"「{top_name}」戏份占比高达 {round(top_share * 100)}%，群像失衡，易成独角戏。",
                            "fix": "给配角安排独立动机/支线，分散叙事焦点。"})
        char_score -= 15
    # 未充分利用 / 工具人 / 未建档
    for n, cnt in sorted(appearances.items(), key=lambda kv: -kv[1]):
        share = round(cnt / total_app * 100)
        # 被动工具人（ recurring 却几乎无主动动作）
        if cnt >= 2 and not char_has_active.get(n) and n in named:
            char_issues.append({"severity": "warning",
                                "text": f"「{n}」出场 {cnt} 次却几乎全是被动反应（被控制/被动作），像工具人。",
                                "fix": "至少给一次主动选择或关键行动，建立人物主体性。"})
            char_score -= 10
        # 未建档
        lib = lib_by_name.get(n)
        if cnt >= 2 and n in named:
            if not lib:
                char_issues.append({"severity": "warning",
                                    "text": f"「{n}」是反复出场的关键角色，却未在角色库建档（缺动机/弧光）。",
                                    "fix": "在「人物设计」补全动机与目标，便于一致性锁与后续展开。"})
                char_score -= 6
            else:
                missing = [f for f in ("motivation", "arc") if not (lib.get(f) or "").strip()]
                if missing:
                    char_issues.append({"severity": "warning",
                                        "text": f"「{n}」已在角色库，但缺少 {('、'.join(missing))}，人物驱动力单薄。",
                                        "fix": "补全动机/人物弧光，让其在压力下有清晰「想要什么」。"})
                    char_score -= 5
    if not char_issues:
        char_issues.append({"severity": "ok", "text": "主要角色都有合理戏份与主动性，未检出明显人物失衡。", "fix": ""})
    char_score = max(0, min(100, char_score))
    report["categories"]["character"] = {
        "score": char_score,
        "label": "人物压力",
        "metrics": {
            "出场角色数": len(appearances),
            "戏份最多": f"{top_name} ({top_cnt}场)",
            "最高占比": f"{round(top_share * 100)}%",
        },
    }

    # ══════════════ 节奏诊断 ══════════════
    pace_issues = []
    pace_score = 100
    # 对白
    with_dialogue = sum(1 for s in scenes if (s.get("dialogue") or []))
    dlg_ratio = with_dialogue / total
    if with_dialogue == 0:
        pace_issues.append({"severity": "warning",
                            "text": "全片零对白，角色没有声音，观众难以建立情感连接与关系。",
                            "fix": "为关键角色补 1-2 句能揭示性格/关系的台词（哪怕画外音）。"})
        pace_score -= 12
    elif dlg_ratio < 0.25:
        pace_issues.append({"severity": "warning",
                            "text": f"仅 {round(dlg_ratio * 100)}% 场景有对白，角色声音偏弱。",
                            "fix": "适度穿插对话调节纯动作节奏，并交代信息。"})
        pace_score -= 6
    # 场景时长
    long_n = sum(1 for r in runtimes if avg_len and r > avg_len * 1.6)
    short_n = sum(1 for r in runtimes if avg_len and r < avg_len * 0.5 and r > 0)
    if long_n:
        pace_issues.append({"severity": "warning", "text": f"有 {long_n} 场明显偏长，易让单场信息稀释。",
                            "fix": "拆分或削减，保持单场「一个核心事件」。"})
        pace_score -= min(15, 5 * long_n)
    if short_n:
        pace_issues.append({"severity": "info", "text": f"有 {short_n} 场偏短，注意是否沦为过场。",
                            "fix": "确认短场承担了转折/钩子功能，否则并入相邻场。"})
        pace_score -= min(10, 4 * short_n)
    # 地点单调（影响出图视觉多样性）
    locs = [ (s.get("location") or "").strip() for s in scenes if (s.get("location") or "").strip() ]
    distinct = len(set(locs))
    loc_ratio = distinct / total if total else 0
    if loc_ratio < 0.5 and total >= 3:
        pace_issues.append({"severity": "warning",
                            "text": f"地点高度重复（{distinct} 个不同地点 / {total} 场），视觉易单调，出图也难出变化。",
                            "fix": "增加场景位移（室内/室外、近/远），用环境反差推动视觉节奏。"})
        pace_score -= 10
    if not pace_issues:
        pace_issues.append({"severity": "ok", "text": "对白、场景时长与地点分布未见明显节奏问题。", "fix": ""})
    pace_score = max(0, min(100, pace_score))
    report["categories"]["pacing"] = {
        "score": pace_score,
        "label": "节奏",
        "metrics": {
            "对白覆盖率": f"{round(dlg_ratio * 100)}%",
            "地点多样性": f"{distinct}/{total}",
            "偏长场": long_n, "偏短场": short_n,
        },
    }

    # ── 汇总（并附加「一键跳转」目标，供前端点击定位到对应阶段修改）──
    report["issues"] = []
    for _label, _lst in (("结构", struct_issues), ("人物压力", char_issues), ("节奏", pace_issues)):
        for _it in _lst:
            _it.setdefault("category", _label)
            if _it.get("severity") != "ok" and "jump" not in _it:
                if _label == "人物压力":
                    # 从「名称」抽取角色名 → 跳到「人物设计」并打开该角色编辑
                    _m = re.search(r"「(.+?)」", _it.get("text", ""))
                    if _m:
                        _it["jump"] = {"stage": "character", "char": _m.group(1)}
                    else:
                        _it["jump"] = {"stage": "character"}
                else:
                    # 结构 / 节奏问题 → 跳到「分镜提示词」核对镜头
                    _it["jump"] = {"stage": "storyboard"}
            report["issues"].append(_it)
    overall = round(struct_score * 0.35 + char_score * 0.35 + pace_score * 0.30)
    report["overall_score"] = overall
    report["overall_grade"] = grade(overall)
    return report


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


def grade(score):
    if score >= 90:
        return "A · 可直接生成"
    if score >= 80:
        return "B · 小修即可"
    if score >= 70:
        return "C · 建议打磨"
    if score >= 60:
        return "D · 需重点修改"
    return "E · 重写风险高"
