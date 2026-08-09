"""统一配置访问层：根路径、.env 加载、火山引擎凭据。

取代散落在各处的 load_dotenv() 调用与重复根路径计算
（script_doctor.py:35,50 / services/inkos_import.py:53 / 各归档脚本）。
所有读取都先确保 .env 已加载且结果缓存，避免重复 IO。
"""
import os

_ENV_LOADED = False
_ROOT = None


def load_env_once():
    """幂等地加载一次 .env。其余模块直接调用本函数，无需各自 load_dotenv()。"""
    global _ENV_LOADED
    if not _ENV_LOADED:
        try:
            import dotenv
            dotenv.load_dotenv()
        except Exception:
            pass
        _ENV_LOADED = True


def root_path():
    """项目根目录（web/ 的上两级），结果缓存。"""
    global _ROOT
    load_env_once()
    if _ROOT is None:
        # __file__ 位于 <root>/web/config.py，上两级即项目根
        _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return _ROOT


def volc_key():
    """火山引擎 Ark API Key（已由 .env 注入环境变量）。"""
    load_env_once()
    return os.environ.get("VOLC_API_KEY", "")


def volc_default_provider():
    """根据 VOLC_DEFAULT 决定是否默认指向火山引擎。"""
    load_env_once()
    if os.environ.get("VOLC_DEFAULT", "1") == "0":
        return os.environ.get("AI_DIRECTOR_DEFAULT_PROVIDER", "")
    return os.environ.get("AI_DIRECTOR_DEFAULT_PROVIDER", "volcengine")
