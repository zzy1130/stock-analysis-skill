"""
配置加载器。

优先级: 环境变量 > config.json
"""

import json
import os
import sys
from pathlib import Path

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"
_APPLY_URL = "https://ai.eastmoney.com/mxClaw"
_cache = None


def _load():
    global _cache
    if _cache is None:
        if _CONFIG_PATH.exists():
            _cache = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        else:
            _cache = {}
    return _cache


def get_em_api_key() -> str:
    """获取 EM_API_KEY，优先环境变量，其次 config.json。"""
    env_key = os.environ.get("EM_API_KEY", "")
    if env_key:
        return env_key
    cfg_key = _load().get("em_api_key", "")
    if cfg_key and cfg_key != "YOUR_EM_API_KEY_HERE":
        return cfg_key
    return ""


def ensure_em_api_key():
    """确保 EM_API_KEY 已设置到环境变量中（供 subprocess 继承）。"""
    key = get_em_api_key()
    if key:
        os.environ["EM_API_KEY"] = key
    elif not os.environ.get("EM_API_KEY"):
        print("[config] ============================================")
        print("[config] 错误: EM_API_KEY 未配置，无法获取行情数据")
        print("[config]")
        print(f"[config] 请前往 {_APPLY_URL} 申请免费 API Key")
        print("[config]")
        print("[config] 配置方式（任选一种）:")
        print("[config]   1. 环境变量: export EM_API_KEY='your_key'")
        print("[config]   2. 配置文件: 复制 config.example.json 为 config.json，填入 key")
        print("[config] ============================================")
        sys.exit(1)
