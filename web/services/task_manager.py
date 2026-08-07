"""异步任务管理器"""
import uuid
import json
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor


class TaskProgress:
    """任务进度回调"""

    def __init__(self, task_id, app):
        self.task_id = task_id
        self.app = app
        self._cancelled = threading.Event()

    def update(self, progress=None, message=None, status=None, logs=None, result=None):
        """更新任务状态"""
        with self.app.app_context():
            from web.models.database import db, TaskModel
            task = TaskModel.query.get(self.task_id)
            if not task:
                return
            if progress is not None:
                task.progress = progress
            if message is not None:
                task.message = message
            if status is not None:
                task.status = status
            if logs is not None:
                existing = json.loads(task.logs) if task.logs else []
                if isinstance(logs, str):
                    existing.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": logs})
                else:
                    existing.append(logs)
                task.logs = json.dumps(existing, ensure_ascii=False)
            if result is not None:
                task.result = json.dumps(result, ensure_ascii=False)
            task.updated_time = datetime.now()
            db.session.commit()

    def is_cancelled(self):
        return self._cancelled.is_set()

    def cancel(self):
        self._cancelled.set()


class TaskManager:
    """异步任务管理器 - 后台线程执行流水线"""

    def __init__(self, app, max_workers=3):
        self.app = app
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.handlers = {}
        self._progress = {}

    def register(self, stage, handler):
        """注册任务处理器"""
        self.handlers[stage] = handler

    def submit(self, stage, name="", project_id=None, chapter_id=None, **kwargs):
        """提交异步任务"""
        task_id = uuid.uuid4().hex[:16]

        with self.app.app_context():
            from web.models.database import db, TaskModel
            task = TaskModel(
                id=task_id,
                name=name,
                stage=stage,
                project_id=project_id,
                chapter_id=chapter_id,
                status="pending",
            )
            db.session.add(task)
            db.session.commit()

        progress = TaskProgress(task_id, self.app)
        self._progress[task_id] = progress

        # 将 chapter_id/project_id 也传给 handler
        kwargs["chapter_id"] = chapter_id
        kwargs["project_id"] = project_id
        self.executor.submit(self._run_task, task_id, stage, progress, **kwargs)
        return task_id

    def _run_task(self, task_id, stage, progress, **kwargs):
        """在线程中执行任务"""
        with self.app.app_context():
            from web.models.database import db, TaskModel
            task = TaskModel.query.get(task_id)
            if task:
                task.status = "running"
                db.session.commit()

            progress.update(logs=f"开始执行: {stage}")

            try:
                handler = self.handlers.get(stage)
                if not handler:
                    raise ValueError(f"未注册的任务处理器: {stage}")

                result = handler(progress=progress, **kwargs)

                progress.update(progress=100, status="success", message="执行完成", result=result or {})
                progress.update(logs="任务完成")
            except Exception as e:
                progress.update(status="fail", message=f"执行失败: {str(e)}")
                progress.update(logs=f"错误: {str(e)}")

    def get_task(self, task_id):
        """获取任务状态"""
        with self.app.app_context():
            from web.models.database import TaskModel
            task = TaskModel.query.get(task_id)
            return task.to_dict() if task else None

    def stop_task(self, task_id):
        """停止任务"""
        progress = self._progress.get(task_id)
        if progress:
            progress.cancel()
            progress.update(status="cancelled", message="已取消")
            return True
        return False

    def list_tasks(self, project_id=None, limit=20):
        """列出任务"""
        with self.app.app_context():
            from web.models.database import TaskModel
            query = TaskModel.query
            if project_id:
                query = query.filter_by(project_id=project_id)
            tasks = query.order_by(TaskModel.created_time.desc()).limit(limit).all()
            return [t.to_dict() for t in tasks]
