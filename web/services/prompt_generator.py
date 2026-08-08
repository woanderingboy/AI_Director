"""剧本 → 电影级视觉 Prompt 生成器"""
from .llm_client import LLMClient


class PromptGenerator:
    """将结构化剧本转换为 AI 图片/视频生成 Prompt"""

    def __init__(self, provider_key="glm", api_key="", model=None, temperature=0.7):
        self.client = LLMClient(provider_key, api_key, model=model)
        self.temperature = temperature

    def generate(self, script_data, globals_context="", custom_prompt=""):
        from web.services.prompt_templates import DEFAULT_PROMPTS
        import json
        system_prompt = DEFAULT_PROMPTS.get("gen_prompts", "")
        if globals_context:
            system_prompt += f"\n\n项目全局设定（必须遵循）：\n{globals_context}"
        if custom_prompt:
            system_prompt += custom_prompt

        context = json.dumps(script_data, ensure_ascii=False, indent=2)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请将以下剧本转换为 AI 视频生成提示词。每个场景根据其 estimated_seconds 拆分为 10-15 秒的镜头。\n\n{context}"},
        ]
        return self.client.chat_json(messages, temperature=self.temperature, max_tokens=8192)

    def generate_from_shots(self, shots, globals_context="", custom_prompt=""):
        """1:1 为剧本已拆好的分镜生成提示词（不再让 LLM 重新拆分镜头）。

        严格保持输入 shots 的 shot_id 列表：不合并、不新增、不丢弃。
        每个输出项至少包含 shot_id / video_prompt / negative_prompt / duration。
        """
        from web.services.prompt_templates import DEFAULT_PROMPTS
        import json

        system_prompt = DEFAULT_PROMPTS.get("gen_prompts", "")
        if globals_context:
            system_prompt += f"\n\n项目全局设定（必须遵循）：\n{globals_context}"
        if custom_prompt:
            system_prompt += custom_prompt

        # 关键约束：禁止重新拆分，直接为每一个已拆分镜生成一条提示词
        system_prompt += (
            "\n\n重要约束（务必遵守）：输入已经是按 10-15 秒切好的分镜列表，"
            "不要重新拆分镜头、不要合并、不要新增或丢弃任何分镜。"
            "请严格为每一个 shot_id 生成一条视觉提示词，输出的 shot_id 必须与输入完全一致（数量、编号均相同）。"
        )

        context = json.dumps(shots, ensure_ascii=False, indent=2)
        shot_n = len(shots)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"以下是已经拆好的 {shot_n} 个分镜（含 shot_id）。"
                f"请为每一个分镜生成 AI 视频/图片生成提示词，每个分镜返回一条记录，"
                f"必须包含与原分镜相同的 shot_id、video_prompt（正向视觉提示词）、"
                f"negative_prompt（负面提示词）、duration（沿用原分镜时长，秒）。\n\n{context}"
            )},
        ]
        data = self.client.chat_json(messages, temperature=self.temperature, max_tokens=8192)
        # 归一化：若模型误返回全本剧本结构（含 scenes），只取 shots 部分
        if isinstance(data, dict) and "shots" not in data and "scenes" in data:
            data = {"shots": []}
        return data
