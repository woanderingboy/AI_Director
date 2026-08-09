"""集中项目目录常量与辅助路径函数。

取代散落的 '02_Projects/<name>/07_Prompt' 等字面量，成为目录命名的唯一真相源。
与 web/__init__.py 中 serve_project_file 的 dir_map 保持完全一致。
"""
import os

from web.config import root_path as _default_root

PROJECTS_DIR = "02_Projects"

# 与 web/__init__.py serve_project_file 的 dir_map 保持一致
PROJECT_SUBDIRS = {
    "story": "04_Story",
    "import": "03_Import",
    "script": "05_Script",
    "storyboard": "06_Storyboard",
    "prompt": "07_Prompt",
    "image": "08_Image",
    "video": "09_Video",
}

# 全局资产库目录（与 01_Global_Assets 对应）
GLOBAL_ASSETS_DIR = "01_Global_Assets"


def project_path(name, root=None):
    """返回 02_Projects/<name> 绝对路径。"""
    return os.path.join(root or _default_root(), PROJECTS_DIR, name)


def project_subdir(name, cat, root=None):
    """返回 02_Projects/<name>/<cat 对应的子目录> 绝对路径。"""
    if cat not in PROJECT_SUBDIRS:
        raise ValueError(f"未知项目子目录分类: {cat}（应为 {list(PROJECT_SUBDIRS)} 之一）")
    return os.path.join(project_path(name, root), PROJECT_SUBDIRS[cat])


def global_assets_path(root=None):
    """返回 01_Global_Assets 绝对路径。"""
    return os.path.join(root or _default_root(), GLOBAL_ASSETS_DIR)
