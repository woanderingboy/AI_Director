"""YAML 配置文件读取工具"""
import os
import yaml


def read_yaml(filepath):
    """读取 YAML 文件并返回字典"""
    if not os.path.exists(filepath):
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(filepath, data):
    """将字典写入 YAML 文件"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
