"""项目路径与结构管理"""
import os


class ProjectService:
    """管理项目的目录结构"""

    SUBDIRS = ["04_Story", "05_Script", "06_Storyboard", "07_Prompt", "08_Image", "09_Video"]

    def __init__(self, root_path):
        self.root_path = root_path
        self.projects_path = os.path.join(root_path, "02_Projects")

    def create_project(self, name):
        """创建项目目录结构"""
        proj_path = os.path.join(self.projects_path, name)
        if os.path.exists(proj_path):
            return proj_path
        for subdir in self.SUBDIRS:
            os.makedirs(os.path.join(proj_path, subdir), exist_ok=True)
        return proj_path

    def get_project_path(self, name):
        return os.path.join(self.projects_path, name)

    def list_projects(self):
        """列出所有项目目录"""
        if not os.path.isdir(self.projects_path):
            return []
        return [
            d for d in os.listdir(self.projects_path)
            if os.path.isdir(os.path.join(self.projects_path, d))
        ]

    def get_project_files(self, project_name, category):
        """列出项目某分类下的文件"""
        cat_map = {
            "story": "04_Story", "script": "05_Script", "storyboard": "06_Storyboard",
            "prompt": "07_Prompt", "image": "08_Image", "video": "09_Video",
        }
        subdir = cat_map.get(category)
        if not subdir:
            return []
        dirpath = os.path.join(self.projects_path, project_name, subdir)
        if not os.path.isdir(dirpath):
            return []
        return sorted(os.listdir(dirpath))
