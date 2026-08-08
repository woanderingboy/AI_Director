"""异步任务管理器"""
import uuid
import json
import time
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor


class TaskProgress:
    """任务进度回调"""

    def __init__(self, task_id, app):
        self.task_id = task_id
        self.app = app
        self._cancelled = threading.Event()
        self._paused = threading.Event()

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

    def is_paused(self):
        return self._paused.is_set()

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def check_interrupt(self):
        """循环体内调用：已取消返回 'cancel'；暂停则阻塞直到恢复（期间被取消也返回 'cancel'）；否则返回 None。

        handler 在每个可中断的检查点（如每轮循环开头）调用它，即可实现「暂停/恢复」与「取消」。"""
        if self._cancelled.is_set():
            return "cancel"
        while self._paused.is_set():
            time.sleep(0.2)
            if self._cancelled.is_set():
                return "cancel"
        return None


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

                # 关键修复：handler 返回后，必须尊重复制消状态，否则「停止」只会是瞬态、
                # 最终仍被覆写为 success，导致用户看到「已取消」但任务其实跑完了。
                if progress.is_cancelled():
                    progress.update(status="cancelled", message="任务已取消")
                    progress.update(logs="任务已取消")
                else:
                    progress.update(progress=100, status="success", message="执行完成", result=result or {})
                    progress.update(logs="任务完成")
            except Exception as e:
                if progress.is_cancelled():
                    progress.update(status="cancelled", message="任务已取消")
                else:
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

    def pause_task(self, task_id):
        """暂停任务（handler 需在循环中调用 check_interrupt / is_paused 才生效）"""
        progress = self._progress.get(task_id)
        if progress:
            progress.pause()
            progress.update(status="paused", message="已暂停")
            return True
        return False

    def resume_task(self, task_id):
        """恢复（继续）任务"""
        progress = self._progress.get(task_id)
        if progress:
            progress.resume()
            progress.update(status="running", message="已恢复运行")
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
