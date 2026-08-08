"""小说创作模块 - 数据库模型"""
from datetime import datetime
from web.models.database import db, ProjectModel


def bump_novel_version(project_id):
    """小说章节/关键节点被修改时，使项目 novel_version +1，用于标记下游产物过期。"""
    if not project_id:
        return
    try:
        p = ProjectModel.query.get(project_id)
        if p:
            p.novel_version = (p.novel_version or 0) + 1
            db.session.commit()
    except Exception:
        db.session.rollback()



class WorldSetting(db.Model):
    """世界观设定"""
    __tablename__ = "world_settings"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    name = db.Column(db.String(200), default="默认世界观")
    world_type = db.Column(db.String(100), default="")  # 世界观类型
    era = db.Column(db.String(100), default="")  # 时代背景
    geography = db.Column(db.Text, default="")  # 地理环境
    power_system = db.Column(db.Text, default="")  # 力量体系
    social_structure = db.Column(db.Text, default="")  # 社会结构
    history = db.Column(db.Text, default="")  # 历史背景
    rules = db.Column(db.Text, default="")  # 核心规则
    culture = db.Column(db.Text, default="")  # 文化风俗
    notes = db.Column(db.Text, default="")  # 补充说明
    ai_context = db.Column(db.Text, default="")  # AI 生成的完整世界观描述
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    characters = db.relationship("NovelCharacter", backref="world", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "project_id": self.project_id, "name": self.name,
            "world_type": self.world_type, "era": self.era,
            "geography": self.geography, "power_system": self.power_system,
            "social_structure": self.social_structure, "history": self.history,
            "rules": self.rules, "culture": self.culture, "notes": self.notes,
            "ai_context": self.ai_context,
            "created_time": str(self.created_time) if self.created_time else None,
            "updated_time": str(self.updated_time) if self.updated_time else None,
            "character_count": len(self.characters),
        }


class NovelCharacter(db.Model):
    """小说角色"""
    __tablename__ = "novel_characters"
    id = db.Column(db.Integer, primary_key=True)
    world_id = db.Column(db.Integer, db.ForeignKey("world_settings.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), default="配角")  # 主角/配角/反派/路人
    gender = db.Column(db.String(20), default="")
    age = db.Column(db.String(50), default="")
    appearance = db.Column(db.Text, default="")  # 外貌描述
    personality = db.Column(db.Text, default="")  # 性格特点
    background = db.Column(db.Text, default="")  # 人物背景
    ability = db.Column(db.Text, default="")  # 能力/技能
    motivation = db.Column(db.Text, default="")  # 动机/目标
    relationships = db.Column(db.Text, default="")  # 人物关系
    arc = db.Column(db.Text, default="")  # 人物弧光/成长线
    key_quotes = db.Column(db.Text, default="")  # 经典台词
    visual_prompt = db.Column(db.Text, default="")  # 视觉化提示词
    consistency_lock = db.Column(db.Boolean, default=False)  # 角色一致性锁：开启后其锁定外观将注入每一帧提示词，防变脸
    locked_prompt = db.Column(db.Text, default="")  # 锁定时注入的视觉描述（默认由外貌+视觉提示词合成）
    notes = db.Column(db.Text, default="")
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "world_id": self.world_id, "project_id": self.project_id,
            "name": self.name, "role": self.role, "gender": self.gender, "age": self.age,
            "appearance": self.appearance, "personality": self.personality,
            "background": self.background, "ability": self.ability,
            "motivation": self.motivation, "relationships": self.relationships,
            "arc": self.arc, "key_quotes": self.key_quotes,
            "visual_prompt": self.visual_prompt,
            "consistency_lock": self.consistency_lock,
            "locked_prompt": self.locked_prompt,
            "notes": self.notes,
            "created_time": str(self.created_time) if self.created_time else None,
            "updated_time": str(self.updated_time) if self.updated_time else None,
        }


class PlotOutline(db.Model):
    """剧情大纲"""
    __tablename__ = "plot_outlines"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    title = db.Column(db.String(200), default="总大纲")
    genre = db.Column(db.String(100), default="")
    theme = db.Column(db.Text, default="")  # 核心主题
    logline = db.Column(db.Text, default="")  # 一句话概括
    synopsis = db.Column(db.Text, default="")  # 故事梗概
    conflict = db.Column(db.Text, default="")  # 核心矛盾
    ending = db.Column(db.Text, default="")  # 结局走向
    ai_context = db.Column(db.Text, default="")  # AI 生成的完整大纲
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    plot_points = db.relationship("PlotPoint", backref="outline", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "project_id": self.project_id, "title": self.title,
            "genre": self.genre, "theme": self.theme, "logline": self.logline,
            "synopsis": self.synopsis, "conflict": self.conflict, "ending": self.ending,
            "ai_context": self.ai_context,
            "created_time": str(self.created_time) if self.created_time else None,
            "updated_time": str(self.updated_time) if self.updated_time else None,
            "point_count": len(self.plot_points),
        }


class PlotPoint(db.Model):
    """关键节点"""
    __tablename__ = "plot_points"
    id = db.Column(db.Integer, primary_key=True)
    outline_id = db.Column(db.Integer, db.ForeignKey("plot_outlines.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    point_type = db.Column(db.String(50), default="剧情点")  # 开场/激励事件/转折/高潮/结局
    sequence = db.Column(db.Integer, default=0)  # 排序
    description = db.Column(db.Text, default="")  # 节点描述
    characters_involved = db.Column(db.Text, default="")  # 涉及角色
    emotional_beat = db.Column(db.Text, default="")  # 情绪节拍
    consequences = db.Column(db.Text, default="")  # 后果/影响
    notes = db.Column(db.Text, default="")
    created_time = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "outline_id": self.outline_id, "project_id": self.project_id,
            "title": self.title, "point_type": self.point_type, "sequence": self.sequence,
            "description": self.description, "characters_involved": self.characters_involved,
            "emotional_beat": self.emotional_beat, "consequences": self.consequences,
            "notes": self.notes,
            "created_time": str(self.created_time) if self.created_time else None,
        }


class NovelChapter(db.Model):
    """小说章节（区别于流水线的 ChapterModel，这里是创作模块的章节）"""
    __tablename__ = "novel_chapters"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    chapter_number = db.Column(db.Integer, default=1)
    title = db.Column(db.String(200), default="")
    summary = db.Column(db.Text, default="")  # 章节概要
    content = db.Column(db.Text, default="")  # 正文
    word_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default="draft")  # draft/writing/done
    notes = db.Column(db.Text, default="")
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    scenes = db.relationship("NovelScene", backref="chapter", lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id, "project_id": self.project_id,
            "chapter_number": self.chapter_number, "title": self.title,
            "summary": self.summary,
            "content": self.content[:300] + "..." if self.content and len(self.content) > 300 else self.content,
            "full_content": self.content,
            "word_count": self.word_count, "status": self.status, "notes": self.notes,
            "created_time": str(self.created_time) if self.created_time else None,
            "updated_time": str(self.updated_time) if self.updated_time else None,
            "scene_count": len(self.scenes),
        }


class NovelScene(db.Model):
    """章节内的场景"""
    __tablename__ = "novel_scenes"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("novel_chapters.id"), nullable=False)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False)
    scene_number = db.Column(db.Integer, default=1)
    title = db.Column(db.String(200), default="")
    location = db.Column(db.String(200), default="")
    time_desc = db.Column(db.String(100), default="")  # 时间描述
    characters = db.Column(db.Text, default="")  # 出场角色
    summary = db.Column(db.Text, default="")  # 场景概要
    content = db.Column(db.Text, default="")  # 场景正文
    mood = db.Column(db.String(100), default="")  # 氛围
    notes = db.Column(db.Text, default="")
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            "id": self.id, "chapter_id": self.chapter_id, "project_id": self.project_id,
            "scene_number": self.scene_number, "title": self.title,
            "location": self.location, "time_desc": self.time_desc,
            "characters": self.characters, "summary": self.summary,
            "content": self.content, "mood": self.mood, "notes": self.notes,
            "created_time": str(self.created_time) if self.created_time else None,
            "updated_time": str(self.updated_time) if self.updated_time else None,
        }
