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
