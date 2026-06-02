from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 main.py 和 tests/ 自身在路径中
MAIN_DIR = Path(__file__).parent.parent
TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(MAIN_DIR))
sys.path.insert(0, str(TESTS_DIR))

from main import DICT_DIR, WordNetDB
from db_backend import DbWordNetDB

sys.path.pop(0)
sys.path.pop(0)


@pytest.fixture(scope="session")
def file_db():
    """基于 dict/ 源文件的内存数据库（session 级别只初始化一次）"""
    return WordNetDB(DICT_DIR)


@pytest.fixture(scope="session")
def db_db():
    """基于 SQLite 的数据库查询后端（session 级别只初始化一次）"""
    db_path = Path(__file__).parent.parent / "db" / "wn.db"
    return DbWordNetDB(db_path)
