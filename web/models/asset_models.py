"""资产版本管理 + 素材打包 数据库模型"""
from datetime import datetime
from web.models.database import db


class AssetVersion(db.Model):
    """资产版本 - 记录每个资产的多个版本"""
    __tablename__ = "asset_versions"
    id = db.Column(db.Integer, primary_key=True)
    # 所属信息
    project_id = db.Column(db.Integer, nullable=True)  # None=全局资产
    asset_type = db.Column(db.String(50), nullable=False)  # world/character/outline/chapter/scene/global_asset
    asset_key = db.Column(db.String(200), nullable=False)  # 资产标识（如角色名、章节号、"Camera/全景"）
    # 版本信息
    version_tag = db.Column(db.String(50), nullable=False)  # v1, v2, ... 或时间戳
    timestamp = db.Column(db.DateTime, default=datetime.now)
    content = db.Column(db.Text, default="")  # 该版本的内容（JSON 或文本）
    content_hash = db.Column(db.String(32), default="")  # 内容摘要，用于去重
    notes = db.Column(db.Text, default="")  # 版本备注
    # 状态
    is_final = db.Column(db.Boolean, default=False)  # 是否为最终确认版
    created_time = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "project_id": self.project_id,
            "asset_type": self.asset_type,
            "asset_key": self.asset_key,
            "version_tag": self.version_tag,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else None,
            "content_preview": (self.content[:200] + "...") if self.content and len(self.content) > 200 else self.content,
            "notes": self.notes,
            "is_final": self.is_final,
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
        }

    def to_dict_full(self):
        d = self.to_dict()
        d["content"] = self.content
        return d


class AssetPackage(db.Model):
    """素材打包记录"""
    __tablename__ = "asset_packages"
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(200), default="")
    description = db.Column(db.Text, default="")
    # 打包内容
    required_assets = db.Column(db.Text, default="[]")  # JSON: 需要的资产列表
    matched_assets = db.Column(db.Text, default="[]")  # JSON: 已匹配的资产
    missing_assets = db.Column(db.Text, default="[]")  # JSON: 缺失的资产
    # 状态
    status = db.Column(db.String(20), default="draft")  # draft/ready/packed
    export_path = db.Column(db.String(500), default="")  # 导出路径
    created_time = db.Column(db.DateTime, default=datetime.now)
    updated_time = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        import json
        return {
            "id": self.id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "required_assets": json.loads(self.required_assets) if self.required_assets else [],
            "matched_assets": json.loads(self.matched_assets) if self.matched_assets else [],
            "missing_assets": json.loads(self.missing_assets) if self.missing_assets else [],
            "status": self.status,
            "export_path": self.export_path,
            "created_time": self.created_time.strftime("%Y-%m-%d %H:%M:%S") if self.created_time else None,
            "updated_time": self.updated_time.strftime("%Y-%m-%d %H:%M:%S") if self.updated_time else None,
        }
