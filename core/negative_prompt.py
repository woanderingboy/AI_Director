"""负面提示词管理"""
import os
import yaml


def load_negative_prompts(root_path):
    """加载全局负面提示词"""
    filepath = os.path.join(root_path, "01_Global_Assets", "negative_prompts.yaml")
    if not os.path.exists(filepath):
        return DEFAULT_NEGATIVE_PROMPTS
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or DEFAULT_NEGATIVE_PROMPTS


DEFAULT_NEGATIVE_PROMPTS = {
    "image": "低质量, 模糊, 变形, 多余肢体, 水印, 文字覆盖, 过度饱和, 卡通风格",
    "video": "抖动, 闪烁, 不一致, 画面撕裂, 伪影, 低帧率",
    "character": "多指, 多手, 面部变形, 比例失调, 解剖错误",
}
