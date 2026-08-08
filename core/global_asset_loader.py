"""全局资产加载器"""
import os
import yaml


class GlobalAssetLoader:
    """加载 01_Global_Assets 下的各类资产"""

    CATEGORIES = ["Camera", "Lighting", "Emotion", "Action", "Transition", "Style", "Template"]

    def __init__(self, root_path):
        self.root_path = root_path
        self.assets_path = os.path.join(root_path, "01_Global_Assets")

    def list_category(self, category):
        """列出某个分类下的所有资产文件（含 YAML 内的名称/描述/提示词，保证 UI 与 YAML 一一对应）"""
        cat_path = os.path.join(self.assets_path, category)
        if not os.path.isdir(cat_path):
            return []
        results = []
        for f in sorted(os.listdir(cat_path)):
            if f.endswith((".yaml", ".yml", ".json", ".txt")):
                name = os.path.splitext(f)[0]
                entry = {
                    "id": f"{category}/{f}",
                    "name": name,
                    "filename": f,
                    "category": category,
                    "path": os.path.join(cat_path, f),
                    "description": "",
                    "prompt": "",
                }
                # 读取 YAML/JSON 内部字段，保证「资产 ID ↔ YAML 内容」视觉对应一致
                try:
                    if f.endswith((".yaml", ".yml")):
                        data = yaml.safe_load(open(os.path.join(cat_path, f), "r", encoding="utf-8")) or {}
                    elif f.endswith(".json"):
                        import json as _json
                        data = _json.load(open(os.path.join(cat_path, f), "r", encoding="utf-8")) or {}
                    else:
                        data = {}
                    if isinstance(data, dict):
                        entry["name"] = data.get("名称") or data.get("name") or name
                        entry["description"] = data.get("描述") or data.get("description") or ""
                        entry["prompt"] = data.get("提示词") or data.get("prompt") or ""
                except Exception:
                    pass
                results.append(entry)
        return results

    def load_asset(self, category, filename):
        """加载单个资产文件内容"""
        filepath = os.path.join(self.assets_path, category, filename)
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            if filename.endswith((".yaml", ".yml")):
                return yaml.safe_load(f) or {}
            elif filename.endswith(".json"):
                import json
                return json.load(f)
            else:
                return {"content": f.read()}

    def list_all(self):
        """列出所有资产"""
        all_assets = {}
        for cat in self.CATEGORIES:
            all_assets[cat] = self.list_category(cat)
        return all_assets

    def save_asset(self, category, filename, content):
        """保存资产文件"""
        filepath = os.path.join(self.assets_path, category, filename)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            if filename.endswith((".yaml", ".yml")):
                yaml.dump(content, f, allow_unicode=True, default_flow_style=False)
            elif filename.endswith(".json"):
                import json
                json.dump(content, f, ensure_ascii=False, indent=2)
            else:
                f.write(content)
        return filepath
