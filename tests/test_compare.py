from __future__ import annotations

import pytest

from compare_utils import compare_lookup_results

# 基础测试单词（覆盖 n/v/a/r 及多词表达）
TEST_WORDS = [
    "dog", "run", "happy", "take", "go", "be",
    "car", "love", "think", "beautiful", "quickly",
    "water", "fire", "eat", "see", "child",
    "good", "bad", "big", "small", "take_over",
    "bank", "light", "break", "head", "line",
    "give", "make", "come", "know", "get",
]

# 指定词性的测试用例（覆盖同形异义、跨词性）
TEST_WORD_POS = [
    ("dog", "n"),
    ("dog", "v"),
    ("run", "v"),
    ("run", "n"),
    ("happy", "a"),
    ("quickly", "r"),
    ("take", "v"),
    ("go", "v"),
    ("break", "v"),
    ("break", "n"),
    ("light", "a"),
    ("light", "n"),
    ("head", "n"),
    ("head", "v"),
    ("bank", "n"),
    ("bank", "v"),
]


@pytest.mark.parametrize("word", TEST_WORDS)
def test_word_lookup_consistency(word, file_db, db_db):
    """不指定词性，对比单词在所有词性中的查询结果。"""
    file_results = file_db.lookup(word)
    db_results = db_db.lookup(word)
    diffs = compare_lookup_results(word, file_results, db_results, file_db)
    assert not diffs, (
        f"单词 '{word}' 文件端与数据库端不一致:\n"
        + "\n".join(f"  - {d}" for d in diffs)
    )


@pytest.mark.parametrize("word,pos", TEST_WORD_POS)
def test_word_pos_lookup_consistency(word, pos, file_db, db_db):
    """指定词性，对比单义词性查询结果。"""
    file_results = file_db.lookup(word, pos)
    db_results = db_db.lookup(word, pos)
    diffs = compare_lookup_results(word, file_results, db_results, file_db)
    assert not diffs, (
        f"单词 '{word}' [{pos}] 文件端与数据库端不一致:\n"
        + "\n".join(f"  - {d}" for d in diffs)
    )
