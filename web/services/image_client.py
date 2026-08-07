"""火山引擎 Seedream 图片生成客户端（方舟 OpenAI 兼容 /images/generations）

- 真实模式：调用火山方舟图片生成接口，返回 b64_json，由调用方落盘。
- 离线/无 Key：返回 None，由 PipelineService 生成占位图，保证链路不中断。
"""
import os
import base64
import requests


class ImageClient:
    def __init__(self, api_key, base_url=None, model=None):
        self.api_key = api_key
        self.base_url = base_url or "https://ark.cn-beijing.volces.com/api/v3/images/generations"
        self.model = model
        self.offline = os.environ.get("AI_DIRECTOR_OFFLINE", "0") == "1"

    def generate(self, prompt, negative_prompt="", size="1024x1024", n=1):
        """生成图片，返回 list[str(b64)]；离线或无 Key 返回 None；失败返回错误信息字符串。"""
        if self.offline or not self.api_key:
            return None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "n": n,
            "response_format": "b64_json",
            "watermark": False,
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        try:
            resp = requests.post(self.base_url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            return [item.get("b64_json") or item.get("url") for item in data]
        except Exception as e:
            return f"[图片生成失败: {str(e)}]"

    def save_b64(self, b64_str, filepath):
        """把 b64 字符串解码写入文件，返回是否成功。"""
        try:
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64_str))
            return True
        except Exception:
            return False
