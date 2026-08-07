"""四阶段流水线服务 - 含时长估算、分镜拆分、全局设定注入"""
import os
import json
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

        provider_key = "glm"
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

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(shot, f, ensure_ascii=False, indent=2)
            saved_files.append(filename)

        if progress:
            progress.update(progress=100, message=f"提示词生成完成，共 {len(shots)} 个镜头", logs="完成")

        return {"shots": len(shots), "files": saved_files}

    def draw_images(self, progress=None, **kwargs):
        """阶段三：Prompt → 图片（当前为占位图）"""
        if progress:
            progress.update(progress=50, message="图片生成（ComfyUI 未接入，使用占位图）", logs="占位图模式")
        return {"status": "placeholder", "message": "ComfyUI 未接入，当前生成占位图"}

    def render_videos(self, progress=None, **kwargs):
        """阶段四：图片 → 视频（moviepy 合成）"""
        if progress:
            progress.update(progress=50, message="视频渲染（moviepy 合成）", logs="视频合成中")
        return {"status": "placeholder", "message": "视频合成功能开发中"}

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
