"""小说 → 结构化剧本生成器（含时长估算）"""
from .llm_client import LLMClient


class ScriptGenerator:
    """将小说文本转换为结构化剧本 JSON"""

    def __init__(self, provider_key="glm", api_key="", model=None, temperature=0.7):
        self.client = LLMClient(provider_key, api_key, model=model)
        self.temperature = temperature

    def generate(self, novel_text, chapter_title="", globals_context="", custom_prompt=""):
        from web.services.prompt_templates import DEFAULT_PROMPTS
        system_prompt = DEFAULT_PROMPTS.get("novel2script", "")
        if globals_context:
            system_prompt += f"\n\n项目全局设定（必须遵循）：\n{globals_context}"
        if custom_prompt:
            system_prompt += custom_prompt

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请将以下小说章节转换为结构化剧本。\n\n章节标题：{chapter_title}\n\n小说原文：\n{novel_text}"},
        ]
        return self.client.chat_json(messages, temperature=self.temperature, max_tokens=8192)
