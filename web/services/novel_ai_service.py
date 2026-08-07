"""小说创作 AI 服务 - 各阶段独立配置"""
import json
from web.services.llm_client import LLMClient


def _get_client_for_stage(stage, project_id=None):
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

            # 阶段独立配置覆盖
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


def _get_stage_prompt(stage, project_id=None):
    """获取阶段独立的自定义 system prompt"""
    from web.models.database import ProjectConfig
    if not project_id:
        return ""
    pc = ProjectConfig.query.filter_by(project_id=project_id).first()
    if not pc:
        return ""
    prompts = json.loads(pc.system_prompts) if pc.system_prompts else {}
    return prompts.get(stage, "")


def _chat(stage, system_prompt, user_content, project_id=None):
    """统一的聊天入口，自动应用阶段配置"""
    client, config = _get_client_for_stage(stage, project_id)

    # 合并自定义 prompt
    custom = _get_stage_prompt(stage, project_id)
    if custom:
        system_prompt = custom + "\n\n" + system_prompt

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return client.chat(messages, temperature=config["temperature"], max_tokens=config["max_tokens"])


def _chat_json(stage, system_prompt, user_content, project_id=None):
    """统一的 JSON 聊天入口"""
    client, config = _get_client_for_stage(stage, project_id)
    custom = _get_stage_prompt(stage, project_id)
    if custom:
        system_prompt = custom + "\n\n" + system_prompt
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return client.chat_json(messages, temperature=config["temperature"], max_tokens=config["max_tokens"])


# ═══════════ 各阶段 AI 函数 ═══════════

def expand_world(user_input, project_id=None):
    """世界观扩展"""
    from web.services.prompt_templates import DEFAULT_PROMPTS
    prompt = DEFAULT_PROMPTS.get("world", "")
    return _chat("world", prompt, f"请根据以下信息扩展为完整的世界观设定：\n\n{user_input}", project_id)


def expand_character(character_info, world_context="", project_id=None):
    """角色扩展"""
    from web.services.prompt_templates import DEFAULT_PROMPTS
    prompt = DEFAULT_PROMPTS.get("character", "")
    if world_context:
        prompt += f"\n\n世界观背景：{world_context}"
    return _chat("character", prompt, f"请根据以下信息扩展为完整的角色设定：\n\n{character_info}", project_id)


def generate_outline(world_context, characters_context, user_hint="", project_id=None):
    """生成剧情大纲"""
    prompt = f"""你是一名专业的编剧和故事架构师。根据世界观和角色设定，创作引人入胜的剧情大纲。
世界观：{world_context}
主要角色：{characters_context}
输出要求：一句话概括(logline)、核心主题、故事梗概(300-500字)、核心矛盾/冲突、结局走向，用中文撰写。"""
    hint = f"用户要求：{user_hint}" if user_hint else ""
    return _chat("outline", prompt, f"请创作剧情大纲。{hint}", project_id)


def generate_plot_points(outline_context, world_context, characters_context, project_id=None):
    """生成关键节点"""
    prompt = f"""你是一名专业的编剧。根据大纲拆解出关键剧情节点。
大纲：{outline_context}
世界观：{world_context}
角色：{characters_context}
输出 JSON 格式：{{"points": [{{"title":"节点标题","point_type":"开场/激励事件/转折/高潮/结局","description":"详细描述","characters_involved":"涉及角色","emotional_beat":"情绪节拍","consequences":"后果/影响"}}]}}
要求：5-10个关键节点，节奏合理，每个节点推动故事发展，用中文撰写。"""
    return _chat_json("plotpoints", prompt, "请根据以上信息生成关键剧情节点。", project_id)


def generate_chapter_summary(chapter_number, plot_points_context, world_context, characters_context, prev_summary="", project_id=None):
    """生成章节概要"""
    prev = f"前一章概要：{prev_summary}" if prev_summary else ""
    prompt = f"""你是一名专业的小说作者。根据关键节点和整体设定，为指定章节生成详细的章节概要。
世界观：{world_context}
角色：{characters_context}
关键节点：{plot_points_context}
{prev}
输出要求：章节标题、章节概要(200-400字)、本章出场角色、本章核心事件、情绪走向，用中文撰写。"""
    return _chat("chapters", prompt, f"请为第{chapter_number}章生成章节概要。", project_id)


def generate_scene_content(scene_info, chapter_context, characters_context, world_context, project_id=None):
    """生成场景正文"""
    prompt = f"""你是一名优秀的小说作者。根据场景设定撰写生动的小说正文。
世界观：{world_context}
角色设定：{characters_context}
章节背景：{chapter_context}
写作要求：文笔流畅画面感强，对话自然符合角色性格，节奏把控得当，适当运用五感描写，用中文撰写，输出纯正文不要标题和注释。"""
    return _chat("scenes", prompt, f"请根据以下场景设定撰写正文：\n\n{scene_info}", project_id)


def polish_content(content, instruction="", project_id=None):
    """润色修改"""
    prompt = "你是一名专业的文字编辑。根据用户的修改要求对小说文本进行润色和修改。保持原文风格和情节，只做指定的修改。输出修改后的完整文本。"
    return _chat("polish", prompt, f"修改要求：{instruction if instruction else '润色文字，提升文笔质量'}\n\n原文：\n{content}", project_id)


def ai_chat_novel(prompt_text, context="", project_id=None):
    """自由对话"""
    ctx = f"当前项目背景：{context}" if context else ""
    prompt = f"""你是一名专业的 AI 小说创作助手。你可以帮助用户：讨论剧情走向、分析角色动机、提供写作建议、解决剧情矛盾、拓展世界观设定。
{ctx}
回答要专业、具体、有建设性。用中文回复。"""
    return _chat("chat", prompt, prompt_text, project_id)
