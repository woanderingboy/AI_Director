"""通用 LLM 客户端 - OpenAI 兼容 API 直连"""
import os
import json
import requests


class LLMClient:
    """支持多服务商的 LLM 客户端"""

    PROVIDERS = {
        "openai": {
            "label": "OpenAI",
            "endpoint": "https://api.openai.com/v1/chat/completions",
        },
        "deepseek": {
            "label": "DeepSeek",
            "endpoint": "https://api.deepseek.com/v1/chat/completions",
        },
        "volcengine": {
            "label": "火山引擎",
            "endpoint": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        },
        "qwen": {
            "label": "通义千问",
            "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        },
        "glm": {
            "label": "智谱 GLM",
            "endpoint": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        },
        "custom": {
            "label": "自定义",
            "endpoint": "",
        },
    }

    PROVIDER_MODELS = {
        "openai": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
        "deepseek": ["deepseek-chat", "deepseek-reasoner"],
        "volcengine": ["glm-5-2-260617", "doubao-seed-2-1-turbo-260628"],
        "qwen": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "glm": ["glm-4-plus", "glm-4-flash", "glm-4-long"],
        "custom": [],
    }

    def __init__(self, provider_key, api_key, base_url=None, model=None):
        self.provider_key = provider_key
        self.api_key = api_key
        self.base_url = base_url or self.PROVIDERS.get(provider_key, {}).get("endpoint", "")
        self.model = model or self._default_model()
        self.offline = os.environ.get("AI_DIRECTOR_OFFLINE", "0") == "1"

    def _default_model(self):
        defaults = {
            "openai": "gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "glm": "glm-4-flash",
            "qwen": "qwen-max",
            "volcengine": "glm-5-2-260617",
        }
        return defaults.get(self.provider_key, "gpt-4o-mini")

    def chat(self, messages, temperature=0.7, max_tokens=4096):
        """发送聊天请求"""
        if self.offline or not self.api_key:
            return self._mock_response(messages)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[LLM 调用失败: {str(e)}]"

    def _mock_response(self, messages):
        """离线 mock 响应"""
        last_msg = messages[-1]["content"] if messages else ""
        if "prompt" in last_msg.lower() or "提示词" in last_msg or "视觉" in last_msg:
            return json.dumps({
                "shots": [
                    {
                        "shot_id": 1,
                        "video_prompt": "电影级画面，暗调风格，全景镜头，城市废墟场景，黄昏光线，一名黑发红瞳青年独自站在废墟高处，暗色风衣随风飘动，俯瞰破败城市，阴沉天空，压抑氛围，电影感构图，浅景深，冷色调",
                        "negative_prompt": "低质量, 模糊, 卡通风格, 过度饱和",
                        "camera": "全景缓慢推进",
                        "lighting": "黄昏侧逆光",
                        "mood": "压抑、孤独",
                    }
                ]
            }, ensure_ascii=False, indent=2)
        elif "剧本" in last_msg or "小说" in last_msg or "结构化" in last_msg:
            return json.dumps({
                "title": "第一幕：停车场重逢",
                "total_duration": 45,
                "scenes": [
                    {
                        "scene_id": 1,
                        "location": "B2停车场",
                        "time": "深夜",
                        "weather": "阴沉",
                        "characters": [
                            {"name": "陈默", "action": "独自巡逻", "emotion": "警觉"}
                        ],
                        "dialogue": [],
                        "camera": "中景缓慢推进",
                        "mood": "压抑、紧张",
                        "description": "深夜停车场，昏暗灯光，一名保安独自巡逻",
                        "estimated_seconds": 15
                    },
                    {
                        "scene_id": 2,
                        "location": "停车场角落",
                        "time": "深夜",
                        "weather": "",
                        "characters": [
                            {"name": "陈默", "action": "制服绑匪", "emotion": "冷静果断"},
                            {"name": "林婉儿", "action": "惊恐", "emotion": "释然"}
                        ],
                        "dialogue": [{"character": "林婉儿", "line": "陈默？"}, {"character": "陈默", "line": "是我，没事了。"}],
                        "camera": "近景→特写",
                        "mood": "紧张到释然",
                        "description": "男人制服三个绑匪，救下女人，四目相对",
                        "estimated_seconds": 20
                    },
                    {
                        "scene_id": 3,
                        "location": "停车场",
                        "time": "深夜",
                        "weather": "",
                        "characters": [{"name": "陈默", "action": "伸手", "emotion": "温柔"}],
                        "dialogue": [],
                        "camera": "特写手部",
                        "mood": "温情",
                        "description": "男人向女人伸出手，灯光洒在两人身上",
                        "estimated_seconds": 10
                    }
                ],
                "characters": [
                    {"name": "陈默", "description": "寸头青年，眼神深邃，穿保安制服"},
                    {"name": "林婉儿", "description": "长发披肩，职业装，惊魂未定"}
                ]
            }, ensure_ascii=False, indent=2)
        else:
            return f"[离线模式 Mock] 收到请求，内容预览: {last_msg[:100]}..."

    def chat_json(self, messages, temperature=0.7, max_tokens=4096):
        """聊天并解析 JSON 响应"""
        raw = self.chat(messages, temperature, max_tokens)
        try:
            # 尝试提取 JSON 块
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0]
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0]
            return json.loads(raw.strip())
        except (json.JSONDecodeError, IndexError):
            return {"raw": raw}
