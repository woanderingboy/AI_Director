"""inkos 书籍产物 → AI Director 创作库 回写服务。

将 inkos（`@actalk/inkos`）生成的书籍目录解析并 upsert 进本项目的
WorldSetting / PlotOutline / PlotPoint / NovelCharacter / NovelChapter，
实现「多智能体写小说 → 自动落到 AI Director 小说创作模块」的衔接。

设计要点：
- inkos 的权威来源已迁移到 outline/ 与 roles/（story_bible.md / character_matrix.md
  被官方标记为「兼容指针——已废弃」），故优先读 outline/story_frame.md、
  outline/volume_map.md、roles/*，缺失时回退到 story_bible.md。
- 幂等：WorldSetting / PlotOutline 按 project 单条 upsert；
  PlotPoint 标记 [inkos]，重导时只替换 inkos 源、保留用户手加节点；
  NovelCharacter 按 (project, name) upsert，且【不覆盖】用户已开启的一致性锁；
  NovelChapter 按 (project, chapter_number) upsert。
- 不自动开启角色一致性锁：inkos 角色档不含外貌/视觉描述，锁住也是空 prompt，
  无意义；用户可在 UI 填好 appearance/visual_prompt 后手动开启。
"""
import os
import re
import json

from web.models.database import db
from web.models.novel_models import (
    WorldSetting, NovelCharacter, PlotOutline, PlotPoint,
    NovelChapter, bump_novel_version,
)

GENRE_MAP = {
    "kehuan": "科幻", "xuanhuan": "玄幻", "yanqing": "言情", "xianxia": "仙侠",
    "zhongshu": "种田", "lingyi": "灵异", "qihuan": "奇幻", "junshi": "军事",
    "lishi": "历史", "xidou": "西幻", "kehuan": "科幻",
}
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


# ───────────────────────── 文本解析工具 ─────────────────────────

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _load_volc_key():
    """优先取环境变量 VOLC_API_KEY，否则直接解析项目 .env。"""
    key = os.environ.get("VOLC_API_KEY", "")
    if key:
        return key
    cand = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
    if os.path.exists(cand):
        try:
            with open(cand, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VOLC_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    return ""


def _get_appearance_client(project_id):
    """返回 (client, config) 用于生成角色外貌；优先项目 character 阶段配置，
    否则回退到火山 glm-5-2-260617（与 inkos 同源 Key）；都没有则返回 (None,None)。"""
    try:
        from web.services.novel_ai_service import _get_client_for_stage
        client, config = _get_client_for_stage("character", project_id)
        if getattr(client, "api_key", ""):
            return client, config
    except Exception:
        pass
    key = _load_volc_key()
    if key:
        from web.services.llm_client import LLMClient
        client = LLMClient("volcengine", key, model="glm-5-2-260617")
        return client, {"temperature": 0.7, "max_tokens": 4096}
    return None, None


def _generate_appearances(project_id, characters):
    """为给定角色批量生成 外貌描述 + 视觉提示词（单次 LLM 调用）。

    Args: characters: list[NovelCharacter]
    Returns: {char_id: (appearance, visual_prompt)}  仅含成功生成的条目
    """
    if not characters:
        return {}
    client, config = _get_appearance_client(project_id)
    if not client:
        return {}
    profiles = []
    for ch in characters:
        bits = [f"【{ch.name}】（{ch.role}）"]
        if ch.personality:
            bits.append("性格：" + ch.personality[:120])
        if ch.background:
            bits.append("背景：" + ch.background[:160])
        if ch.motivation:
            bits.append("动机：" + ch.motivation[:120])
        if ch.arc:
            bits.append("弧光：" + ch.arc[:120])
        if ch.relationships:
            bits.append("关系：" + ch.relationships[:120])
        profiles.append("\n".join(bits))
    user_content = (
        "你是为小说角色设计视觉形象的美术指导。请基于下列角色档案，"
        "为每个角色生成两部分：\n"
        "1) appearance：自然的中文外貌描述（年龄感、发型、瞳色、身材/衣着风格、特征标记），"
        "40-90 字，供人阅读并用于角色一致性锁定。\n"
        "2) visual_prompt：适合 AI 文生图的视觉提示词，中文，含镜头感、光线、风格、细节，"
        "60-120 字，须与 appearance 一致。\n\n"
        "严格返回 JSON 对象，键为角色名，值为 {\"appearance\":\"...\",\"visual_prompt\":\"...\"}。"
        "不要输出任何解释文字，只输出 JSON。\n\n"
        + "\n\n".join(profiles)
    )
    system = "你是资深角色美术指导，擅长把文字人设转化为准确、可用于图像生成的视觉描述。只输出 JSON。"
    try:
        data = client.chat_json(
            [{"role": "system", "content": system},
             {"role": "user", "content": user_content}],
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 4096) or 4096,
        )
    except Exception:
        return {}
    result = {}
    if isinstance(data, dict):
        for ch in characters:
            item = data.get(ch.name)
            if isinstance(item, dict):
                ap = (item.get("appearance") or "").strip()
                vp = (item.get("visual_prompt") or "").strip()
                if ap or vp:
                    result[ch.id] = (ap, vp)
    return result


def _section_startswith(text, heading_prefix):
    """取 markdown 中以 `## <heading_prefix>...` 开头的段落，到下个 ## 为止。"""
    m = re.search(r'^##\s*' + re.escape(heading_prefix), text, re.M)
    if not m:
        return ""
    start = m.end()
    nxt = re.search(r'^##\s', text[start:], re.M)
    return (text[start: start + nxt.start()] if nxt else text[start:]).strip()


def _parse_role_sections(text):
    """按 `## 标题` 拆分角色档为 {标题: 内容}。"""
    parts = {}
    matches = list(re.finditer(r'^##\s*(.+?)\s*$', text, re.M))
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        parts[title] = text[start:end].strip()
    return parts


VOL_RE = re.compile(r'第([一二三四五六七八九十]+)卷')
END_RE = re.compile(
    r'第([一二三四五六七八九十]+)卷卷尾[：:]\s*(.*?)(?=第[一二三四五六七八九十]+卷卷尾|##\s*节奏原则|\Z)',
    re.S,
)


def _first(sec, keys):
    """在角色档各 section 中按候选标题顺序取第一个非空内容。"""
    for k in keys:
        if sec.get(k):
            return sec[k]
    return ""


def _split_volumes(section_text):
    """把「各卷主题与情绪曲线」段落拆成 [(cn, name, body), ...]。"""
    matches = list(VOL_RE.finditer(section_text))
    vols = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section_text)
        body = section_text[start:end].strip()
        name_m = re.match(r'["“](.+?)["”]', body)
        name = name_m.group(1) if name_m else ""
        vols.append((m.group(1), name, body))
    return vols


# ───────────────────────── 主入口 ─────────────────────────

def import_inkos_book(project_id, book_dir, source_tag="inkos",
                      gen_appearance=True, auto_lock_main=False):
    """解析 inkos 书籍目录并 upsert 进 AI Director。

    Args:
        project_id:        AI Director 项目 id
        book_dir:          inkos 书籍目录（含 book.json 与 story/ 的目录）
        source_tag:        写入 PlotPoint.notes 的来源标记，用于重导时区分
        gen_appearance:    是否用 LLM 为角色批量生成 外貌描述 + 视觉提示词
        auto_lock_main:    是否对（导入的）主角自动开启一致性锁（需已生成外貌）

    Returns:
        dict 含各模型 新增/更新 计数与 skipped 原因
    """
    book_dir = os.path.abspath(book_dir)
    story_dir = os.path.join(book_dir, "story")
    if not os.path.isdir(story_dir):
        raise ValueError(f"无效的 inkos 书籍目录（缺少 story/）：{book_dir}")

    book_json = {}
    bj_path = os.path.join(book_dir, "book.json")
    if os.path.exists(bj_path):
        try:
            book_json = json.loads(_read(bj_path)) or {}
        except Exception:
            book_json = {}

    title = book_json.get("title") or book_json.get("id") or os.path.basename(book_dir)
    genre_raw = book_json.get("genre", "")
    genre = GENRE_MAP.get(genre_raw, genre_raw)
    platform = book_json.get("platform", "")
    target_chapters = book_json.get("targetChapters", "")

    # ── 读取权威文本（优先 outline/，回退 story_bible.md）──
    frame = _read(os.path.join(story_dir, "outline", "story_frame.md"))
    if not frame.strip():
        frame = _read(os.path.join(story_dir, "story_bible.md"))
    volume = _read(os.path.join(story_dir, "outline", "volume_map.md"))
    rules = _read(os.path.join(story_dir, "book_rules.md"))
    style = _read(os.path.join(story_dir, "style_guide.md"))
    hooks = _read(os.path.join(story_dir, "pending_hooks.md"))
    intent = _read(os.path.join(story_dir, "author_intent.md"))

    stat = {"world": 0, "outline": 0, "plot_points_added": 0,
            "plot_points_removed": 0, "characters_added": 0,
            "characters_updated": 0, "chapters_added": 0,
            "chapters_updated": 0, "appearances_generated": 0,
            "auto_locked": 0, "notes": []}

    # ── 1) WorldSetting（单条 upsert）──
    world = WorldSetting.query.filter_by(project_id=project_id).first()
    if not world:
        world = WorldSetting(project_id=project_id)
        db.session.add(world)
        stat["world"] = 1
    else:
        stat["world"] = 0
    world.name = title
    world.world_type = genre
    world.rules = rules
    world.ai_context = "\n\n".join(
        x for x in [frame, volume, rules, style, hooks] if x.strip()
    )
    world.notes = (
        f"来源：inkos 书籍《{title}》\n"
        f"类型：{genre_raw}  平台：{platform}  目标章节：{target_chapters}\n"
        f"简报：{intent.strip()}"
    )
    db.session.commit()

    # ── 2) PlotOutline（单条 upsert）──
    outline = PlotOutline.query.filter_by(project_id=project_id).first()
    if not outline:
        outline = PlotOutline(project_id=project_id)
        db.session.add(outline)
        stat["outline"] = 1
    outline.title = title
    outline.genre = genre
    outline.theme = _section_startswith(frame, "主题与基调")
    outline.logline = _extract_logline(intent)
    outline.conflict = _section_startswith(frame, "核心冲突")
    outline.ending = _section_startswith(frame, "终局方向")
    outline.synopsis = outline.theme  # 主题与基调本身即最佳梗概
    outline.ai_context = frame
    db.session.commit()

    # ── 3) PlotPoint（来自 volume_map 五卷；按 [inkos] 标记替换）──
    # 先删旧的 inkos 源节点，保留用户手加
    old = PlotPoint.query.filter_by(project_id=project_id).filter(
        PlotPoint.notes.like(f"%[{source_tag}]%")
    ).all()
    for p in old:
        db.session.delete(p)
    stat["plot_points_removed"] = len(old)

    end_map = {m.group(1): m.group(2).strip() for m in END_RE.finditer(volume)}
    theme_vols = _split_volumes(_section_startswith(volume, "各卷主题与情绪曲线"))
    for cn, name, body in theme_vols:
        seq = CN_NUM.get(cn, 0)
        pt = PlotPoint(
            outline_id=outline.id,
            project_id=project_id,
            title=f"第{cn}卷 {name}".strip(),
            point_type="分卷",
            sequence=seq,
            description=body,
            consequences=end_map.get(cn, ""),
            notes=f"[{source_tag}] 来自 inkos volume_map",
        )
        db.session.add(pt)
        stat["plot_points_added"] += 1
    db.session.commit()

    # ── 4) NovelCharacter（按名 upsert，保留一致性锁）──
    roles_dir = os.path.join(story_dir, "roles")
    imported_char_ids = []
    if os.path.isdir(roles_dir):
        for folder in sorted(os.listdir(roles_dir)):
            fpath = os.path.join(roles_dir, folder)
            if not os.path.isdir(fpath):
                continue
            role_label = "主角" if folder == "主要角色" else "配角"
            for fn in sorted(os.listdir(fpath)):
                if not fn.endswith(".md"):
                    continue
                name = os.path.splitext(fn)[0]
                text = _read(os.path.join(fpath, fn))
                sec = _parse_role_sections(text)
                char = NovelCharacter.query.filter_by(
                    project_id=project_id, name=name
                ).first()
                is_new = char is None
                if is_new:
                    char = NovelCharacter(
                        project_id=project_id,
                        world_id=world.id,
                        name=name,
                    )
                    db.session.add(char)
                    stat["characters_added"] += 1
                else:
                    stat["characters_updated"] += 1
                # 文本字段刷新（即便已存在也用 inkos 最新档覆盖）
                char.world_id = world.id
                char.role = role_label
                char.personality = _join(
                    sec.get("核心标签", ""), sec.get("反差细节", "")
                )
                # 次要角色档标题与主角色不同：用候选标题顺序兼容
                char.background = _first(
                    sec, ["人物小传（过往经历）", "人物小传", "当前现状（第 0 章初始状态）", "当前现状"]
                )
                char.motivation = _first(sec, ["内在驱动"])
                char.arc = _join(
                    _first(sec, ["主角弧线（起点 → 终点 → 代价）", "主角弧线"]),
                    sec.get("成长弧光", ""),
                )
                char.relationships = _first(sec, ["关系网络", "与主角关系", "关系"])
                char.notes = text + f"\n\n[来源 inkos roles/{folder}/{fn}]"
                # 一致性锁由用户掌控：仅当从未锁定时才保持默认，已锁不覆盖
                db.session.commit()
                imported_char_ids.append(char.id)

    # ── 4.5) 自动生成外貌提示词（仅对本次导入、且 appearance 为空的角色）──
    if gen_appearance and imported_char_ids:
        imported_chars = NovelCharacter.query.filter(
            NovelCharacter.id.in_(imported_char_ids)
        ).all()
        empty_chars = [c for c in imported_chars if not (c.appearance or "").strip()]
        if empty_chars:
            ap_map = _generate_appearances(project_id, empty_chars)
            for c in empty_chars:
                if c.id in ap_map:
                    ap, vp = ap_map[c.id]
                    if ap:
                        c.appearance = ap
                    if vp:
                        c.visual_prompt = vp
                    db.session.commit()
            stat["appearances_generated"] = len(ap_map)

    # ── 4.6) 自动开启主角一致性锁（需已生成外貌/视觉提示词）──
    if auto_lock_main and imported_char_ids:
        for c in NovelCharacter.query.filter(
            NovelCharacter.id.in_(imported_char_ids)
        ).all():
            if c.role == "主角" and not c.consistency_lock:
                if (c.appearance or c.visual_prompt) and (
                    c.appearance or ""
                ).strip():
                    c.consistency_lock = True
                    c.locked_prompt = "；".join(
                        [x for x in [c.appearance, c.visual_prompt] if x and x.strip()]
                    )
                    db.session.commit()
                    stat["auto_locked"] += 1

    # ── 5) NovelChapter（格式自适应；write next 落盘后才非空）──
    chapters_dir = os.path.join(book_dir, "chapters")
    chapter_entries = []
    idx_path = os.path.join(chapters_dir, "index.json")
    if os.path.exists(idx_path):
        try:
            chapter_entries = json.loads(_read(idx_path)) or []
        except Exception:
            chapter_entries = []
    # 兜底：直接扫描 chapters/*.md
    md_files = []
    if os.path.isdir(chapters_dir):
        md_files = [
            os.path.join(chapters_dir, f)
            for f in sorted(os.listdir(chapters_dir))
            if f.endswith(".md")
        ]

    processed = set()
    for entry in chapter_entries:
        if not isinstance(entry, dict):
            continue
        num = int(entry.get("number") or entry.get("chapter_number") or 0)
        if not num:
            continue
        ctitle = entry.get("title", f"第{num}章")
        content = entry.get("content", "")
        # 若 index 只含元信息，从文件读取正文
        cfile = entry.get("file") or entry.get("path")
        if (not content) and cfile:
            content = _read(os.path.join(chapters_dir, cfile))
        processed.add(num)
        _upsert_chapter(project_id, num, ctitle, content, stat)

    for mf in md_files:
        base = os.path.splitext(os.path.basename(mf))[0]
        m = re.match(r'(\d+)', base)
        num = int(m.group(1)) if m else len(processed) + 1
        if num in processed:
            continue
        content = _read(mf)
        # 尝试解析 YAML frontmatter 取标题
        ctitle = f"第{num}章"
        fm = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.S)
        if fm:
            for line in fm.group(1).splitlines():
                if line.lower().startswith("title:"):
                    ctitle = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
            content = content[fm.end():]
        processed.add(num)
        _upsert_chapter(project_id, num, ctitle, content, stat)

    if not chapter_entries and not md_files:
        stat["notes"].append(
            "chapters/ 暂无可导入章节（inkos write next 尚未把章节落盘到 chapters/）。"
        )

    # 小说创作相关数据已变更 → 标记下游产物过期
    bump_novel_version(project_id)
    db.session.commit()

    return stat


def _upsert_chapter(project_id, num, title, content, stat):
    ch = NovelChapter.query.filter_by(project_id=project_id, chapter_number=num).first()
    if not ch:
        ch = NovelChapter(project_id=project_id, chapter_number=num)
        db.session.add(ch)
        stat["chapters_added"] += 1
    else:
        stat["chapters_updated"] += 1
    ch.title = title
    ch.content = content
    ch.word_count = len(content or "")
    ch.status = "done"
    db.session.commit()


def _join(*parts):
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _extract_logline(intent):
    """从 author_intent.md 抽取「核心：...」一行作为 logline。"""
    m = re.search(r'核心[：:]\s*(.+)', intent)
    if m:
        return m.group(1).strip()
    # 退而取第一行非空
    for line in intent.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""
