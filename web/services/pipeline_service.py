"""四阶段流水线服务 - 含时长估算、分镜拆分、全局设定注入"""
import os
import json
import glob
import base64
from .script_generator import ScriptGenerator
from .prompt_generator import PromptGenerator
from .llm_client import LLMClient


class PipelineService:
    """四阶段流水线：小说→剧本→Prompt→图片→视频"""

    def __init__(self, root_path):
        self.root_path = root_path
        self.projects_path = os.path.join(root_path, "02_Projects")

    def _get_project_path(self, project_name):
        return os.path.join(self.projects_path, project_name)

    def _get_global_settings(self, project_id=None):
        """读取项目全局设定"""
        if not project_id:
            return {}
        try:
            from web.models.database import ProjectConfig
            pc = ProjectConfig.query.filter_by(project_id=project_id).first()
            if pc and pc.system_prompts:
                prompts = json.loads(pc.system_prompts)
                return prompts.get("__globals__", {})
        except Exception:
            pass
        return {}

    def _get_client_for_stage(self, stage, project_id=None):
        """根据阶段获取独立配置的 LLM 客户端"""
        from web.models.database import Provider, ProjectConfig

        provider_key = os.environ.get("AI_DIRECTOR_DEFAULT_PROVIDER", "glm")
        api_key = ""
        model = None
        temperature = 0.7
        max_tokens = 4096

        if project_id:
            pc = ProjectConfig.query.filter_by(project_id=project_id).first()
            if pc:
                if pc.provider_key:
                    provider_key = pc.provider_key
                if pc.model:
                    model = pc.model
                if pc.temperature:
                    temperature = pc.temperature
                if pc.max_tokens:
                    max_tokens = pc.max_tokens
                stage_configs = json.loads(pc.llm_configs) if pc.llm_configs else {}
                sc = stage_configs.get(stage, {})
                if sc.get("provider_key"):
                    provider_key = sc["provider_key"]
                if sc.get("model"):
                    model = sc["model"]
                if sc.get("temperature") is not None:
                    temperature = sc["temperature"]
                if sc.get("max_tokens") is not None:
                    max_tokens = sc["max_tokens"]

        provider = Provider.query.get(provider_key)
        if provider and provider.api_key:
            api_key = provider.api_key

        return LLMClient(provider_key, api_key, model=model), {
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    def _get_stage_prompt(self, stage, project_id=None):
        """获取阶段提示词（自定义 + 默认模板）"""
        from web.services.prompt_templates import DEFAULT_PROMPTS

        # 默认模板
        default = DEFAULT_PROMPTS.get(stage, "")

        # 用户自定义（追加到默认之后）
        custom = ""
        if project_id:
            from web.models.database import ProjectConfig
            pc = ProjectConfig.query.filter_by(project_id=project_id).first()
            if pc:
                prompts = json.loads(pc.system_prompts) if pc.system_prompts else {}
                custom = prompts.get(stage, "")

        parts = [default]
        if custom:
            parts.append(f"\n自定义指令：\n{custom}")
        return "\n".join(parts)

    def _build_consistency_lock_map(self, project_id=None):
        """构建角色一致性锁映射：{角色名: 锁定注入的视觉描述}。仅含开启锁且描述非空者。"""
        if not project_id:
            return {}
        try:
            from web.models.novel_models import NovelCharacter
            chars = NovelCharacter.query.filter_by(project_id=project_id).all()
            lock_map = {}
            for c in chars:
                if getattr(c, "consistency_lock", False):
                    lp = (c.locked_prompt or "").strip()
                    if not lp:
                        # 未手动填锁定描述时，用外貌+视觉提示词自动合成
                        lp = "；".join([x for x in [c.appearance, c.visual_prompt] if x and x.strip()])
                    if lp:
                        lock_map[c.name] = lp
            return lock_map
        except Exception:
            return {}

    def _build_globals_context(self, project_id=None):
        """构建全局设定上下文字符串，含角色视觉档案"""
        gs = self._get_global_settings(project_id)
        if not gs:
            return ""
        parts = []
        if gs.get("art_style"):
            parts.append(f"画风：{gs['art_style']}")
        if gs.get("color_palette"):
            parts.append(f"色彩：{gs['color_palette']}")
        if gs.get("lighting"):
            parts.append(f"光线：{gs['lighting']}")
        if gs.get("mood"):
            parts.append(f"氛围：{gs['mood']}")
        if gs.get("positive_prompts"):
            parts.append(f"正向提示词：{gs['positive_prompts']}")
        if gs.get("negative_prompts"):
            parts.append(f"负面提示词：{gs['negative_prompts']}")

        # 角色视觉档案
        profiles = gs.get("character_profiles", {})
        if profiles:
            parts.append("\n角色视觉档案：")
            for name, p in profiles.items():
                char_info = [f"  {name}"]
                if p.get("appearance"):
                    char_info.append(f"    外貌：{p['appearance']}")
                if p.get("visual_prompt"):
                    char_info.append(f"    视觉提示词：{p['visual_prompt']}")
                if p.get("voice"):
                    char_info.append(f"    音色：{p['voice']}")
                if p.get("color_palette"):
                    char_info.append(f"    专属色彩：{p['color_palette']}")
                outfits = p.get("outfits", {})
                if outfits:
                    char_info.append(f"    服装系统：")
                    for o_name, o_data in outfits.items():
                        desc = o_data.get("description", o_data.get("prompt", ""))
                        char_info.append(f"      {o_name}：{desc}")
                parts.append("\n".join(char_info))

        return "\n".join(parts) if parts else ""

    def _split_shots(self, script_data, project_id=None):
        """将剧本场景拆分为 10-15 秒的分镜头"""
        scenes = script_data.get("scenes", [])
        if not scenes:
            return script_data

        gs = self._get_global_settings(project_id)
        shots = []
        shot_id = 1
        total_duration = 0

        for scene in scenes:
            # 估算场景时长（基于对话数和描述长度）
            dialogue_count = len(scene.get("dialogue", []))
            desc_len = len(scene.get("description", scene.get("action", "")))
            est_seconds = max(10, min(60, dialogue_count * 8 + desc_len // 20))

            # 拆分为 10-15 秒的镜头
            remaining = est_seconds
            while remaining > 0:
                shot_duration = min(15, max(10, remaining))
                total_duration += shot_duration

                shot = {
                    "shot_id": shot_id,
                    "scene_id": scene.get("scene_id", 0),
                    "duration": shot_duration,
                    "location": scene.get("location", ""),
                    "time": scene.get("time", ""),
                    "characters": scene.get("characters", []),
                    "camera": scene.get("camera", "中景"),
                    "mood": scene.get("mood", ""),
                    "description": scene.get("description", ""),
                    "dialogue": scene.get("dialogue", [])[:1] if shot_id % 2 == 1 else [],  # 交替分配对话
                }

                # 注入全局设定
                if gs.get("art_style"):
                    shot["art_style"] = gs["art_style"]
                if gs.get("color_palette"):
                    shot["color_palette"] = gs["color_palette"]

                shots.append(shot)
                shot_id += 1
                remaining -= shot_duration

        script_data["shots"] = shots
        script_data["total_duration"] = total_duration
        script_data["shot_count"] = len(shots)
        return script_data

    # ═══════════ 四阶段流水线 ═══════════

    def novel_to_script(self, project_name=None, chapter_id=None, progress=None, **kwargs):
        """阶段一：小说 → 结构化剧本（含时长估算 + 分镜拆分）"""
        if progress:
            progress.update(progress=10, message="正在读取小说文本...", logs="读取小说章节")

        from web.models.database import db, ChapterModel, ScriptModel, ProjectModel
        from web.models.novel_models import NovelChapter

        chapter = None
        novel_ch = None
        project_id = kwargs.get("project_id")

        if chapter_id:
            chapter = ChapterModel.query.get(chapter_id)
            if chapter:
                novel_text = chapter.content
                chapter_title = chapter.title
                project = ProjectModel.query.get(chapter.project_id)
                project_name = project.name
            else:
                novel_ch = NovelChapter.query.get(chapter_id)
                if novel_ch:
                    novel_text = novel_ch.content or ""
                    chapter_title = novel_ch.title
                    project = ProjectModel.query.get(novel_ch.project_id)
                    project_name = project.name if project else project_name
                else:
                    raise ValueError(f"章节不存在: {chapter_id}")
        else:
            raise ValueError("必须指定 chapter_id")

        if not project_id:
            project_id = chapter.project_id if chapter else (novel_ch.project_id if novel_ch else None)

        # 早期守卫：空/纯空白小说不应浪费一次 LLM 调用，直接清晰报错
        if not novel_text or not novel_text.strip():
            raise ValueError("小说内容为空，无法生成剧本。请先填写章节正文后再试。")

        # 构建全局设定上下文
        globals_ctx = self._build_globals_context(project_id)
        custom_prompt = self._get_stage_prompt("novel2script", project_id)

        client, llm_config = self._get_client_for_stage("novel2script", project_id)
        generator = ScriptGenerator(provider_key=client.provider_key, api_key=client.api_key, model=client.model)
        generator.client = client
        generator.temperature = llm_config["temperature"]

        if progress:
            progress.update(progress=30, message="正在调用 LLM 生成剧本...", logs="调用大模型")

        # 传入全局设定和自定义 prompt
        script_data = generator.generate(novel_text, chapter_title, globals_ctx, custom_prompt)

        # 防御：大模型可能返回非 JSON / 截断 / 空结构（如小说过长触发 max_tokens 截断）。
        # 此时 chat_json 会回退为 {"raw": ...}，必须显式报错，避免静默写出 0 镜头的空剧本。
        if not isinstance(script_data, dict) or not script_data.get("scenes"):
            raw_preview = (script_data.get("raw", "") if isinstance(script_data, dict) else str(script_data))[:120]
            raise ValueError(
                "大模型未返回有效的结构化剧本（可能为截断/非 JSON/空结构）。"
                f"请检查网络与模型配额，或精简本章小说后重试。原始片段：{raw_preview}"
            )

        if progress:
            progress.update(progress=60, message="正在拆分分镜头（10-15秒）...", logs="拆分镜头")

        # 拆分分镜头
        script_data = self._split_shots(script_data, project_id)

        if progress:
            progress.update(progress=70, message="正在保存剧本...", logs="保存剧本文件")

        proj_path = self._get_project_path(project_name)
        script_dir = os.path.join(proj_path, "05_Script")
        os.makedirs(script_dir, exist_ok=True)

        filename = f"{chapter_title}_script.json"
        filepath = os.path.join(script_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(script_data, f, ensure_ascii=False, indent=2)

        shot_count = len(script_data.get("shots", []))
        total_duration = script_data.get("total_duration", 0)
        ch_id = chapter.id if chapter else None
        nov_ch_id = novel_ch.id if novel_ch else None
        script_model = ScriptModel(
            chapter_id=ch_id,
            novel_chapter_id=nov_ch_id,
            filename=filename,
            file_path=filepath,
            shot_count=shot_count,
        )
        db.session.add(script_model)
        db.session.commit()

        if progress:
            progress.update(progress=100, message=f"剧本完成：{shot_count} 个镜头，总时长 {total_duration}秒", logs="完成")

        return {"filename": filename, "shot_count": shot_count, "path": filepath, "total_duration": total_duration}

    def gen_prompts(self, project_name=None, chapter_id=None, script_id=None, progress=None, **kwargs):
        """阶段二：剧本 → 视觉提示词（注入全局设定）"""
        if progress:
            progress.update(progress=10, message="正在读取剧本...", logs="读取剧本文件")

        from web.models.database import db, ScriptModel, ChapterModel

        if script_id:
            script = ScriptModel.query.get(script_id)
            if not script:
                raise ValueError(f"剧本不存在: {script_id}")
            with open(script.file_path, "r", encoding="utf-8") as f:
                script_data = json.load(f)
            chapter = ChapterModel.query.get(script.chapter_id) if script.chapter_id else None
        else:
            raise ValueError("必须指定 script_id")

        proj_id = chapter.project_id if chapter else kwargs.get("project_id")

        # 从剧本 JSON 抽取每个分镜出现的角色（按 shot_id 索引），用于注入一致性锁
        shot_characters = {}
        shot_locations = {}
        for sh in script_data.get("shots", []):
            sid = sh.get("shot_id")
            names = []
            for c in sh.get("characters", []) or []:
                if isinstance(c, dict) and c.get("name"):
                    names.append(c["name"])
                elif isinstance(c, str):
                    names.append(c)
            if sid is not None:
                shot_characters[sid] = names
                loc = (sh.get("location") or "").strip()
                if loc:
                    shot_locations[sid] = loc

        # 构建「角色一致性锁」映射：开启锁且锁定描述非空的角色 → 注入字符串
        locked_map = self._build_consistency_lock_map(proj_id)

        # 构建全局设定上下文
        globals_ctx = self._build_globals_context(proj_id)
        custom_prompt = self._get_stage_prompt("gen_prompts", proj_id)

        client, llm_config = self._get_client_for_stage("gen_prompts", proj_id)
        prompt_gen = PromptGenerator(provider_key=client.provider_key, api_key=client.api_key, model=client.model)
        prompt_gen.client = client
        prompt_gen.temperature = llm_config["temperature"]

        if progress:
            progress.update(progress=30, message="正在生成视觉提示词...", logs="调用大模型")

        prompt_data = prompt_gen.generate(script_data, globals_context=globals_ctx, custom_prompt=custom_prompt)

        if progress:
            progress.update(progress=70, message="正在保存提示词...", logs="保存 Prompt 文件")

        proj_path = self._get_project_path(project_name or "千渡念莞")
        prompt_dir = os.path.join(proj_path, "07_Prompt")
        os.makedirs(prompt_dir, exist_ok=True)

        shots = prompt_data.get("shots", [])
        ch_title = "unknown"
        if chapter:
            ch_title = chapter.title
        elif script_data and isinstance(script_data, dict):
            ch_title = script_data.get("title", "unknown")
        elif project_name:
            ch_title = project_name

        saved_files = []
        for i, shot in enumerate(shots):
            shot_id = shot.get("shot_id", i + 1)
            safe_title = ch_title.replace(" ", "_").replace("/", "-")[:30]
            filename = f"{safe_title}_prompt_S{shot_id:02d}.json"
            filepath = os.path.join(prompt_dir, filename)

            # 注入全局设定到每个 prompt
            gs = self._get_global_settings(proj_id)
            if gs.get("positive_prompts") and "video_prompt" in shot:
                shot["video_prompt"] = shot["video_prompt"] + ", " + gs["positive_prompts"]
            if gs.get("negative_prompts") and "negative_prompt" in shot:
                shot["negative_prompt"] = shot["negative_prompt"] + ", " + gs["negative_prompts"]

            # 注入「角色一致性锁」：把锁定角色的外观描述强制写入该分镜视频提示词，防变脸
            shot_chars = shot_characters.get(shot_id, [])
            locked_chars = []
            if locked_map and shot_chars:
                vp = shot.get("video_prompt", "")
                for name in shot_chars:
                    lp = locked_map.get(name)
                    if not lp:
                        continue
                    tag = f"【角色一致性锁定·{name}】{lp}"
                    # 幂等：若该角色锁描述已存在则不重复追加
                    if tag not in vp:
                        vp = (vp + "，" + tag) if vp else tag
                        locked_chars.append(name)
                if locked_chars:
                    shot["video_prompt"] = vp
            # 把出场角色与已锁定角色落盘，供分镜画布反查与显示锁徽章
            shot["characters"] = shot_chars
            loc = shot_locations.get(shot_id)
            if loc:
                shot["location"] = loc
            if locked_chars:
                shot["locked_characters"] = locked_chars

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(shot, f, ensure_ascii=False, indent=2)
            saved_files.append(filename)

        if progress:
            progress.update(progress=100, message=f"提示词生成完成，共 {len(shots)} 个镜头", logs="完成")

        return {"shots": len(shots), "files": saved_files}

    def _resolve_project_name(self, project_id, project_name):
        """根据 project_id 反查项目名（project_name 缺失时）"""
        if project_name:
            return project_name
        if project_id:
            try:
                from web.models.database import ProjectModel
                p = ProjectModel.query.get(project_id)
                if p:
                    return p.name
            except Exception:
                pass
        return None

    def _get_image_client(self):
        """取图片生成客户端：优先火山引擎（含 seedream 模型的 provider）"""
        from web.models.database import Provider
        # 默认服务商
        default_key = os.environ.get("AI_DIRECTOR_DEFAULT_PROVIDER", "volcengine")
        # 优先找带 seedream 图片模型的 provider（注意：仅匹配 seedream，避免误匹配 doubao-seed 文本模型）
        target = None
        for key in (default_key, "volcengine"):
            p = Provider.query.get(key)
            if p and p.api_key and any("seedream" in m.lower() for m in p.get_models()):
                target = p
                break
        if not target:
            return None, None
        image_models = [m for m in target.get_models() if "seedream" in m.lower()]
        if not image_models:
            return None, None  # 没有 seedream 模型时不硬调文本模型，交由占位逻辑处理
        model = image_models[0]
        from .image_client import ImageClient
        return ImageClient(api_key=target.api_key, model=model), model

    def draw_images(self, progress=None, **kwargs):
        """阶段三：Prompt → 图片（火山引擎 Seedream 真实生成；离线/无 Key 自动占位）"""
        from web.models.database import Provider

        project_name = self._resolve_project_name(kwargs.get("project_id"), kwargs.get("project_name"))
        if not project_name:
            return {"status": "error", "message": "无法确定项目，无法生成图片"}
        proj_path = self._get_project_path(project_name)
        prompt_dir = os.path.join(proj_path, "07_Prompt")
        image_dir = os.path.join(proj_path, "08_Image")
        os.makedirs(image_dir, exist_ok=True)

        prompt_files = sorted(glob.glob(os.path.join(prompt_dir, "*_prompt_*.json")))
        if not prompt_files:
            if progress:
                progress.update(progress=100, message="无提示词文件，跳过图片生成", logs="无提示词")
            return {"status": "skipped", "message": "07_Prompt 下无提示词文件"}

        client, model = self._get_image_client()
        results = []
        total = len(prompt_files)
        for i, pf in enumerate(prompt_files):
            try:
                with open(pf, "r", encoding="utf-8") as f:
                    shot = json.load(f)
            except Exception:
                shot = {}
            prompt = shot.get("video_prompt", "")
            neg = shot.get("negative_prompt", "")
            base = os.path.splitext(os.path.basename(pf))[0]
            img_path = os.path.join(image_dir, base + ".png")

            if progress:
                progress.update(progress=int(15 + 75 * i / total),
                                message=f"生成第 {i+1}/{total} 张图 [{model or '占位'}]",
                                logs=f"Seedream: {model}")

            gen = client.generate(prompt, neg) if client else None
            if isinstance(gen, list) and gen and gen[0] and client.save_b64(gen[0], img_path):
                results.append(img_path)
            elif isinstance(gen, str) and gen.startswith("[图片生成失败"):
                # 真实调用失败：写占位图并附带错误说明
                self._write_placeholder(img_path, f"生成失败: {gen}")
                results.append(img_path)
            else:
                # 离线或无 Key：占位图
                self._write_placeholder(img_path, prompt[:120] or "离线占位图")
                results.append(img_path)

        if progress:
            progress.update(progress=100,
                            message=f"图片生成完成：{len(results)} 张（模型 {model or '占位'}）", logs="完成")
        return {"status": "ok", "model": model, "count": len(results), "images": results}

    def _write_placeholder(self, filepath, text):
        """生成一张带文字的占位 PNG（离线/失败时使用）"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            img = Image.new("RGB", (512, 512), (28, 28, 36))
            draw = ImageDraw.Draw(img)
            try:
                font = ImageFont.load_default()
            except Exception:
                font = None
            # 简单换行绘制
            lines = []
            for seg in (text or "").split(", "):
                lines.append(seg)
            y = 20
            for line in lines[:18]:
                draw.text((16, y), line[:40], fill=(200, 200, 210), font=font)
                y += 26
            img.save(filepath)
        except Exception:
            # 极端兜底：纯色块
            try:
                from PIL import Image
                Image.new("RGB", (256, 256), (40, 40, 50)).save(filepath)
            except Exception:
                pass

    def render_videos(self, progress=None, **kwargs):
        """阶段四：图片 → 视频（本地 moviepy 合成，无需视频生成 API）。

        同时把「角色一致性锁」强制注入每镜视频合成提示词（与图像阶段一致），
        防止后续接 I2V 模型时角色变脸；并输出 video_consistency.json 侧车供人工核对。
        """
        project_name = self._resolve_project_name(kwargs.get("project_id"), kwargs.get("project_name"))
        if not project_name:
            return {"status": "error", "message": "无法确定项目，无法合成视频"}
        proj_path = self._get_project_path(project_name)
        prompt_dir = os.path.join(proj_path, "07_Prompt")
        image_dir = os.path.join(proj_path, "08_Image")
        video_dir = os.path.join(proj_path, "09_Video")
        os.makedirs(video_dir, exist_ok=True)

        prompt_files = sorted(glob.glob(os.path.join(prompt_dir, "*_prompt_*.json")))
        if not prompt_files:
            if progress:
                progress.update(progress=100, message="07_Prompt 无提示词，跳过视频合成", logs="无提示词")
            return {"status": "skipped", "message": "07_Prompt 下无提示词文件"}

        # 一致性锁映射（防变脸，视频阶段同样强制注入）
        locked_map = self._build_consistency_lock_map(kwargs.get("project_id"))

        # 收集图片（按文件名 stem 关联提示词）
        images_by_stem = {}
        for ext in ("*.png", "*.jpg"):
            for p in glob.glob(os.path.join(image_dir, ext)):
                images_by_stem[os.path.splitext(os.path.basename(p))[0]] = p
        if not images_by_stem:
            if progress:
                progress.update(progress=100, message="08_Image 无图片，跳过视频合成", logs="无图片")
            return {"status": "skipped", "message": "08_Image 下无图片"}

        try:
            # 兼容 moviepy v1 / v2 的导入方式
            try:
                from moviepy.editor import ImageClip, concatenate_videoclips
            except Exception:
                from moviepy import ImageClip, concatenate_videoclips

            clips = []
            consistency = {}  # shot_stem -> {shot_id, duration, locked_characters, video_prompt}
            total = len(prompt_files)
            for i, pf in enumerate(prompt_files):
                stem = os.path.splitext(os.path.basename(pf))[0]
                img = images_by_stem.get(stem)
                if not img:
                    continue
                try:
                    with open(pf, "r", encoding="utf-8") as f:
                        shot = json.load(f)
                except Exception:
                    shot = {}

                # 时长：优先用分镜 duration，兜底 3 秒
                try:
                    dur = float(shot.get("duration") or 3)
                except Exception:
                    dur = 3.0
                dur = max(1.0, min(15.0, dur))

                # 视频合成提示词（I2V 用）：把一致性锁强注入，防变脸
                vp = shot.get("video_prompt", "")
                shot_chars = shot.get("characters", []) or []
                locked_chars = []
                if locked_map and shot_chars:
                    for name in shot_chars:
                        lp = locked_map.get(name)
                        if not lp:
                            continue
                        tag = f"【角色一致性锁定·{name}】{lp}"
                        if tag not in vp:
                            vp = (vp + "，" + tag) if vp else tag
                        locked_chars.append(name)
                consistency[stem] = {
                    "shot_id": shot.get("shot_id"),
                    "duration": dur,
                    "locked_characters": locked_chars,
                    "video_prompt": vp,
                }

                if progress:
                    progress.update(progress=int(20 + 70 * i / total),
                                    message=f"合成第 {i + 1}/{total} 镜（锁:{len(locked_chars)}）...",
                                    logs="moviepy 合成")
                clips.append(ImageClip(img).with_duration(dur))

            if not clips:
                return {"status": "skipped", "message": "没有可合成的镜头"}

            video = concatenate_videoclips(clips, method="compose")
            out = os.path.join(video_dir, f"{project_name}_preview.mp4")
            video.write_videofile(out, fps=24, codec="libx264", audio=False)

            # 侧车：视频阶段一致性锁报告，供 I2V 与人工核对
            sidecar = os.path.join(video_dir, "video_consistency.json")
            with open(sidecar, "w", encoding="utf-8") as f:
                json.dump({
                    "video": os.path.basename(out),
                    "shots": consistency,
                    "locked_shot_count": sum(1 for v in consistency.values() if v["locked_characters"]),
                }, f, ensure_ascii=False, indent=2)

            locked_n = sum(1 for v in consistency.values() if v["locked_characters"])
            if progress:
                progress.update(progress=100,
                                message=f"视频合成完成：{out}（{len(clips)} 镜，{locked_n} 镜带锁）", logs="完成")
            return {"status": "ok", "video": out, "count": len(clips),
                    "locked_shot_count": locked_n, "consistency_file": sidecar}
        except Exception as e:
            if progress:
                progress.update(progress=100,
                                message=f"视频合成跳过（缺少 moviepy/ffmpeg）：{str(e)[:60]}", logs="合成跳过")
            return {"status": "skipped", "message": f"视频合成不可用: {str(e)}"}

    def run_all(self, project_name=None, chapter_id=None, progress=None, **kwargs):
        """一键全流程"""
        if progress:
            progress.update(progress=5, message="开始全流程...", logs="启动四阶段流水线")

        kwargs.pop("script_id", None)
        kwargs.pop("chapter_id", None)
        kwargs.pop("project_name", None)

        result = {}

        result["script"] = self.novel_to_script(
            project_name=project_name, chapter_id=chapter_id, progress=progress, **kwargs
        )

        if progress and not progress.is_cancelled():
            from web.models.database import ScriptModel
            project_id = kwargs.get("project_id")
            scripts = ScriptModel.query.filter_by(novel_chapter_id=chapter_id).all()
            if not scripts:
                scripts = ScriptModel.query.filter_by(chapter_id=chapter_id).all()
            script_id = scripts[-1].id if scripts else None
            if script_id:
                result["prompts"] = self.gen_prompts(
                    project_name=project_name, chapter_id=chapter_id,
                    script_id=script_id, progress=progress, **kwargs
                )

        if progress and not progress.is_cancelled():
            result["images"] = self.draw_images(progress=progress, **kwargs)

        if progress and not progress.is_cancelled():
            result["videos"] = self.render_videos(progress=progress, **kwargs)

        return result
