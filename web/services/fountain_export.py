"""将内部剧本 JSON 导出为专业编剧通用格式。

支持两种输出：
- Fountain：纯文本剧本标记语言（https://fountain.io），可被 Highland、WriterDuet、
  Final Draft(插件) 等几乎所有编剧软件读取。
- FDX：Final Draft 原生 XML 格式，可被 Final Draft 直接打开。

内部剧本 JSON 结构（由流水线生成）：
{
  "title": "...",
  "total_duration": 30,
  "characters": [{"name","description"}],
  "scenes": [{"scene_id","location","time","weather","characters":[{name,action,emotion}],
              "dialogue":[{"character","line","parenthetical"}],"camera","mood",
              "description","estimated_seconds"}],
  "shots": [...]   # 可选，细粒度单元，结构与 scene 类似
}
"""

import re
import xml.sax.saxutils as saxutils

# 室外判定：出现这些词视为 EXT.（室外）
_EXT_HINTS = re.compile(
    r"(室外|户外|室[外]|街道|大街|公路|马路|海滩|海边|江边|湖边|河边|山顶|山野|"
    r"广场|公园|桥[上头]|天台|露台|院子|门外|旷野|沙漠|山林|草原|麦田|码头|"
    r"河岸|屋顶|车站外|机场外|露营地|田野)"
)

# 时段映射（按优先级匹配）
_TIME_MAP = [
    (re.compile(r"(深夜|午夜|半夜|子夜|凌晨)"), "NIGHT"),
    (re.compile(r"(黎明|清晨|拂晓|破晓|凌晨)"), "DAWN"),
    (re.compile(r"(白天|日间|白日|正午|中午|晌午|日间)"), "DAY"),
    (re.compile(r"(黄昏|傍晚|夕阳|日落|暮色|余晖)"), "DUSK"),
    (re.compile(r"(夜晚|夜里|夜间|夜幕)"), "NIGHT"),
]


def _is_ext(location: str) -> bool:
    return bool(_EXT_HINTS.search(location or ""))


def _map_time(time_str: str) -> str:
    t = (time_str or "").strip()
    for pat, val in _TIME_MAP:
        if pat.search(t):
            return val
    # 没有明确时段时的默认
    return "DAY"


def _scene_heading(location: str, time_str: str) -> str:
    kind = "EXT" if _is_ext(location) else "INT"
    loc = (location or "未知名").strip()
    return f"{kind}. {loc} - {_map_time(time_str)}"


def _clean_char_name(name: str) -> str:
    """角色提示词在 Fountain/FDX 中作为对白提示（cue），保持原名即可。"""
    return (name or "").strip()


def _dialogue_blocks(dialogue):
    """dialogue 可能为 list[dict] 或 list[str]，统一返回 [(character, parenthetical, line)]。"""
    out = []
    if not dialogue:
        return out
    for d in dialogue:
        if isinstance(d, str):
            out.append(("", "", d))
            continue
        if isinstance(d, dict):
            char = d.get("character") or d.get("speaker") or d.get("name") or ""
            line = d.get("line") or d.get("text") or d.get("content") or ""
            par = d.get("parenthetical") or d.get("note") or ""
            out.append((_clean_char_name(char), par, line))
    return out


def build_blocks(data: dict, char_meta: dict = None) -> list:
    """把剧本 JSON 转换成统一的块序列，便于序列化为任意格式。

    char_meta: 可选，{角色名: {"locked": bool, "appearance": str, "locked_prompt": str}}
               用于把「已开启一致性锁」角色的外观描述写成真人编剧对照注释。

    块结构: {"kind": ..., "text": ...}
    kind ∈ title | lock_header | lock_line | scene_heading | action |
          character | parenthetical | dialogue | transition
    """
    blocks = []
    title = (data.get("title") or "").strip()
    if title:
        blocks.append({"kind": "title", "text": title})

    # 角色一致性锁定注释（仅「已锁定」角色，供真人编剧对照外观，防 AI 出图变脸）
    lock_notes = []
    if char_meta:
        for name, meta in char_meta.items():
            if not meta or not meta.get("locked"):
                continue
            desc = (meta.get("locked_prompt") or meta.get("appearance") or "").strip()
            if desc:
                lock_notes.append(f"{name}：{desc}")
    if lock_notes:
        blocks.append({"kind": "lock_header", "text": "角色一致性锁定（真人编剧对照参考）"})
        for ln in lock_notes:
            blocks.append({"kind": "lock_line", "text": ln})

    scenes = data.get("scenes") or []
    shots = data.get("shots") or []
    units = scenes if scenes else shots
    use_scenes = bool(scenes)

    for u in units:
        loc = u.get("location", "")
        tim = u.get("time", "")
        blocks.append({"kind": "scene_heading", "text": _scene_heading(loc, tim)})

        desc = (u.get("description") or "").strip()
        if desc:
            blocks.append({"kind": "action", "text": desc})

        # 镜头/摄影提示：仅在 shots 层级补充，避免与场景描述重复
        cam = (u.get("camera") or "").strip()
        if cam and not use_scenes:
            blocks.append({"kind": "action", "text": f"【镜头】{cam}"})

        # 对白
        for char, par, line in _dialogue_blocks(u.get("dialogue")):
            if char:
                blocks.append({"kind": "character", "text": char})
            if par:
                blocks.append({"kind": "parenthetical", "text": par})
            if line:
                blocks.append({"kind": "dialogue", "text": line})

    if blocks:
        blocks.append({"kind": "transition", "text": "FADE OUT."})
    return blocks


def to_fountain(blocks: list) -> str:
    """序列化为 Fountain 纯文本。"""
    lines = []
    for b in blocks:
        k = b["kind"]
        t = (b["text"] or "").strip()
        if k == "title":
            lines.append(f"Title: {t}")
            lines.append("")  # 标题页与正文之间空行
        elif k == "lock_header":
            lines.append(f"/* ── {t} ── */")
            lines.append("")
        elif k == "lock_line":
            lines.append(f"/* 🔒 {t} */")
            lines.append("")
        elif k == "scene_heading":
            lines.append(t)
            lines.append("")
        elif k == "action":
            lines.append(t)
            lines.append("")
        elif k == "character":
            lines.append(t)
        elif k == "parenthetical":
            lines.append(f"({t})")
        elif k == "dialogue":
            lines.append(t)
            lines.append("")
        elif k == "transition":
            lines.append(t)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _esc(t: str) -> str:
    return saxutils.escape(t)


def to_fdx(blocks: list) -> str:
    """序列化为 Final Draft (FDX) XML。"""
    title = ""
    paras = []
    type_map = {
        "scene_heading": "Scene Heading",
        "action": "Action",
        "character": "Character",
        "parenthetical": "Parenthetical",
        "dialogue": "Dialogue",
        "transition": "Transition",
    }
    for b in blocks:
        k = b["kind"]
        t = (b["text"] or "").strip()
        if k == "title":
            title = t
            continue
        if k == "lock_header":
            paras.append(f'    <ScriptNote Color="0" Title="角色一致性锁定">{_esc(t)}</ScriptNote>')
            continue
        if k == "lock_line":
            paras.append(f'    <ScriptNote Color="0" Title="锁定">{_esc("🔒 " + t)}</ScriptNote>')
            continue
        pt = type_map.get(k, "Action")
        paras.append(f'    <Paragraph Type="{pt}">{_esc(t)}</Paragraph>')

    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>']
    xml.append('<FinalDraft DocumentType="Script" Template="No" Version="1">')
    if title:
        xml.append(f"  <Title>{_esc(title)}</Title>")
    xml.append("  <Content>")
    xml.extend(paras)
    xml.append("  </Content>")
    xml.append("</FinalDraft>")
    return "\n".join(xml) + "\n"


if __name__ == "__main__":
    import json
    import sys

    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        d = json.load(fh)
    blks = build_blocks(d)
    print("=== FOUNTAIN ===")
    print(to_fountain(blks))
    print("=== FDX ===")
    print(to_fdx(blks))
