import os
from flask import Flask, render_template, send_from_directory
from flask_cors import CORS
import dotenv

dotenv.load_dotenv()
from .models.database import db
from .routes.projects import bp as projects_bp
from .routes.chapters import bp as chapters_bp
from .routes.global_assets import bp as global_assets_bp
from .routes.pipeline import bp as pipeline_bp
from .routes.tasks import bp as tasks_bp
from .routes.assets import bp as assets_bp
from .routes.project_config import bp as project_config_bp
from .routes.prompt_library import bp as prompt_library_bp
from .routes.providers import bp as providers_bp
from .routes.novel_world import bp as novel_world_bp
from .routes.novel_characters import bp as novel_characters_bp
from .routes.novel_outline import bp as novel_outline_bp
from .routes.novel_chapters import bp as novel_chapters_bp
from .routes.novel_chat import bp as novel_chat_bp
from .routes.asset_versions import bp as asset_versions_bp
from .routes.asset_packages import bp as asset_packages_bp
from .routes.project_globals import bp as project_globals_bp
from .routes.import_files import bp as import_files_bp
from .routes.storyboard import bp as storyboard_bp
from .routes.entities import bp as entities_bp
from .routes.script_doctor import bp as script_doctor_bp
from .routes.script_export import bp as script_export_bp
from .routes.subtitle import bp as subtitle_bp
from .services.task_manager import TaskManager
from .services.pipeline_service import PipelineService

ROOT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _migrate_consistency_lock(db):
    """为 novel_characters 表补齐 consistency_lock / locked_prompt 列（仅新增，不删数据）"""
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)
        existing = {c["name"] for c in inspector.get_columns("novel_characters")}
        needed = {
            "consistency_lock": "BOOLEAN DEFAULT 0",
            "locked_prompt": "TEXT DEFAULT ''",
        }
        for col, ddl in needed.items():
            if col not in existing:
                with db.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE novel_characters ADD COLUMN {col} {ddl}"))
                    conn.commit()
    except Exception:
        # 迁移失败不应阻断启动；下次启动会重试
        pass


def _migrate_novel_version(db):
    """为 projects / scripts 表补齐 novel_version / stale 列（仅新增，不删数据）"""
    try:
        from sqlalchemy import text, inspect
        inspector = inspect(db.engine)

        proj_existing = {c["name"] for c in inspector.get_columns("projects")}
        proj_needed = {"novel_version": "INTEGER DEFAULT 0"}
        for col, ddl in proj_needed.items():
            if col not in proj_existing:
                with db.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE projects ADD COLUMN {col} {ddl}"))
                    conn.commit()

        scr_existing = {c["name"] for c in inspector.get_columns("scripts")}
        scr_needed = {
            "novel_version": "INTEGER DEFAULT 0",
            "stale": "BOOLEAN DEFAULT 0",
        }
        for col, ddl in scr_needed.items():
            if col not in scr_existing:
                with db.engine.connect() as conn:
                    conn.execute(text(f"ALTER TABLE scripts ADD COLUMN {col} {ddl}"))
                    conn.commit()
    except Exception:
        pass


def create_app(config_overrides=None):
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=os.path.join(os.path.dirname(__file__), "static"),
    )
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-123")
    db_path = os.path.join(ROOT_PATH, "04_Output", "ai_video_data.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"] = False
    app.config["ROOT_PATH"] = ROOT_PATH
    if config_overrides:
        app.config.update(config_overrides)

    CORS(app)
    db.init_app(app)

    app.task_manager = TaskManager(app, max_workers=3)
    pipeline_svc = PipelineService(ROOT_PATH)
    app.task_manager.register("pipeline.novel2script", pipeline_svc.novel_to_script)
    app.task_manager.register("pipeline.gen_prompts", pipeline_svc.gen_prompts)
    app.task_manager.register("pipeline.draw_images", pipeline_svc.draw_images)
    app.task_manager.register("pipeline.render_videos", pipeline_svc.render_videos)
    app.task_manager.register("pipeline.run_all", pipeline_svc.run_all)

    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(chapters_bp, url_prefix="/api")
    app.register_blueprint(global_assets_bp, url_prefix="/api/global-assets")
    app.register_blueprint(pipeline_bp, url_prefix="/api/pipeline")
    app.register_blueprint(tasks_bp, url_prefix="/api/tasks")
    app.register_blueprint(assets_bp, url_prefix="/api/assets")
    app.register_blueprint(project_config_bp, url_prefix="/api")
    app.register_blueprint(prompt_library_bp, url_prefix="/api/prompt-library")
    app.register_blueprint(providers_bp, url_prefix="/api/providers")
    app.register_blueprint(novel_world_bp, url_prefix="/api/novel")
    app.register_blueprint(novel_characters_bp, url_prefix="/api/novel")
    app.register_blueprint(novel_outline_bp, url_prefix="/api/novel")
    app.register_blueprint(novel_chapters_bp, url_prefix="/api/novel")
    app.register_blueprint(novel_chat_bp, url_prefix="/api/novel")
    app.register_blueprint(asset_versions_bp, url_prefix="/api/asset-versions")
    app.register_blueprint(asset_packages_bp, url_prefix="/api/asset-packages")
    app.register_blueprint(project_globals_bp, url_prefix="/api")
    app.register_blueprint(import_files_bp, url_prefix="/api/import")
    app.register_blueprint(storyboard_bp, url_prefix="/api/storyboard")
    app.register_blueprint(entities_bp, url_prefix="/api/entities")
    app.register_blueprint(script_doctor_bp, url_prefix="/api")
    app.register_blueprint(script_export_bp, url_prefix="/api/script-export")
    app.register_blueprint(subtitle_bp, url_prefix="/api/subtitle")

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    @app.route("/files/<project>/<cat>/<path:filename>")
    def serve_project_file(project, cat, filename):
        proj_root = os.path.join(ROOT_PATH, "02_Projects", project)
        dir_map = {
            "story": "04_Story", "script": "05_Script", "storyboard": "06_Storyboard",
            "prompt": "07_Prompt", "image": "08_Image", "video": "09_Video",
        }
        if cat not in dir_map:
            return {"error": "unknown category"}, 400
        target_dir = os.path.join(proj_root, dir_map[cat])
        return send_from_directory(target_dir, filename)

    with app.app_context():
        db.create_all()
        # 导入小说创作模块模型（确保表被创建）
        from .models import novel_models  # noqa: F401
        db.create_all()
        # 列迁移：为已存在的 novel_characters 表补齐一致性锁字段（不破坏已有数据）
        _migrate_consistency_lock(db)
        # 列迁移：为 projects / scripts 表补齐 novel_version / stale（下游过期追踪）
        _migrate_novel_version(db)
        from .models.database import Provider
        from .services.llm_client import LLMClient
        for key, info in LLMClient.PROVIDERS.items():
            if not Provider.query.get(key):
                p = Provider(key=key, name=info["label"], base_url=info.get("endpoint", ""), api_key="", is_builtin=True)
                p.set_models(LLMClient.PROVIDER_MODELS.get(key, []))
                db.session.add(p)
        db.session.commit()

        # 从 .env 注入火山引擎（方舟 Ark）真实配置：API Key + 模型清单 + 默认服务商
        volc_key = os.environ.get("VOLC_API_KEY", "")
        if volc_key:
            vp = Provider.query.get("volcengine")
            if vp:
                vp.api_key = volc_key
                text_models = [m.strip() for m in os.environ.get(
                    "VOLC_TEXT_MODELS", "glm-5-2-260617,doubao-seed-2-1-turbo-260628"
                ).split(",") if m.strip()]
                image_models = [m.strip() for m in os.environ.get(
                    "VOLC_IMAGE_MODELS", ""
                ).split(",") if m.strip()]
                # 文本模型在前（作为对话默认），图片模型在后（供后续生图集成选用，额度有限）
                vp.set_models(text_models + image_models)
                db.session.add(vp)
                # 默认服务商指向火山引擎（除非用户显式设置了其他默认）
                if os.environ.get("VOLC_DEFAULT", "1") != "0":
                    os.environ.setdefault("AI_DIRECTOR_DEFAULT_PROVIDER", "volcengine")
                db.session.commit()

    return app
