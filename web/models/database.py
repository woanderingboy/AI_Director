from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class ProjectModel(db.Model):
    __tablename__ = "projects"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    description = db.Column(db.Text, default="")
    genre = db.Column(db.String(50), default="剧情")
    novel_version = db.Column(db.Integer, default=0)  # 小说/关键节点编辑时递增；下游产物据此判断是否过期
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    chapters = db.relationship("ChapterModel", backref="project", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "genre": self.genre,
            "novel_version": self.novel_version or 0,
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
            "updated_time": self.updated_time.strftime("%Y-%m-%d %H:%M:%S") if self.updated_time else None,
            "chapter_count": len(self.chapters),
        }


class ChapterModel(db.Model):
    __tablename__ = "chapters"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, default="")
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    scripts = db.relationship("ScriptModel", backref="chapter", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "filename": self.filename,
            "content": self.content[:500] + "..." if self.content and len(self.content) > 500 else self.content,
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
            "updated_time": self.updated_time.strftime("%Y-%m-%d %H:%M:%S") if self.updated_time else None,
            "script_count": len(self.scripts),
        }


class ScriptModel(db.Model):
    __tablename__ = "scripts"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=True)
    novel_chapter_id = db.Column(db.Integer, nullable=True)  # 关联 novel_chapters.id
    filename = db.Column(db.String(300), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    shot_count = db.Column(db.Integer, default=0)
    novel_version = db.Column(db.Integer, default=0)  # 剧本生成时基于的小说版本
    stale = db.Column(db.Boolean, default=False)  # 上游小说已更新、本剧本待重生成
    created_time = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "novel_chapter_id": self.novel_chapter_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "shot_count": self.shot_count,
            "novel_version": self.novel_version or 0,
            "stale": bool(self.stale),
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
        }


class TaskModel(db.Model):
    __tablename__ = "tasks"
    id = db.Column(db.String(64), primary_key=True)
    name = db.Column(db.String(200), default="")
    stage = db.Column(db.String(50), default="")
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=True)
    status = db.Column(db.String(20), default="pending")
    progress = db.Column(db.Integer, default=0)
    message = db.Column(db.Text, default="")
    logs = db.Column(db.Text, default="[]")
    result = db.Column(db.Text, default="{}")
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "name": self.name,
            "stage": self.stage,
            "project_id": self.project_id,
            "chapter_id": self.chapter_id,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "logs": json.loads(self.logs) if self.logs else [],
            "result": json.loads(self.result) if self.result else {},
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
            "updated_time": self.updated_time.strftime("%Y-%m-%d %H:%M:%S") if self.updated_time else None,
        }


class Provider(db.Model):
    __tablename__ = "providers"
    key = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    base_url = db.Column(db.String(500), default="")
    api_key = db.Column(db.String(500), default="")
    is_builtin = db.Column(db.Boolean, default=False)
    models_json = db.Column(db.Text, default="[]")

    def set_models(self, models):
        import json
        self.models_json = json.dumps(models, ensure_ascii=False)

    def get_models(self):
        import json
        return json.loads(self.models_json) if self.models_json else []

    def to_dict(self):
        return {
            "key": self.key,
            "name": self.name,
            "base_url": self.base_url,
            "has_key": bool(self.api_key),
            "is_builtin": self.is_builtin,
            "models": self.get_models(),
        }


class ProjectConfig(db.Model):
    __tablename__ = "project_configs"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, unique=True)
    provider_key = db.Column(db.String(50), default="")
    model = db.Column(db.String(100), default="")
    temperature = db.Column(db.Float, default=0.7)
    max_tokens = db.Column(db.Integer, default=4096)
    system_prompts = db.Column(db.Text, default="{}")
    llm_configs = db.Column(db.Text, default="{}")

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "provider_key": self.provider_key,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "system_prompts": json.loads(self.system_prompts) if self.system_prompts else {},
            "llm_configs": json.loads(self.llm_configs) if self.llm_configs else {},
        }


class PromptTerm(db.Model):
    __tablename__ = "prompt_terms"
    id = db.Column(db.Integer, primary_key=True)
    term = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), default="")
    use_count = db.Column(db.Integer, default=0)
    manual_weight = db.Column(db.Float, default=1.0)
    created_time = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "term": self.term,
            "category": self.category,
            "use_count": self.use_count,
            "manual_weight": self.manual_weight,
        }
