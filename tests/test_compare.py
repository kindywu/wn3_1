from __future__ import annotations

from pathlib import Path

import pytest

from compare_utils import compare_lookup_results

DICT_DIR = Path(__file__).parent.parent / "dict"
POS_TO_FILE = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}


def _load_all_lemmas() -> list[str]:
    """从 dict/index.* 源文件提取所有唯一 lemma。"""
    lemmas: set[str] = set()
    for pos, fname in POS_TO_FILE.items():
        path = DICT_DIR / f"index.{fname}"
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("  ") or not line.strip() or line.startswith("This"):
                    continue
                lemma = line.strip().split()[0]
                lemmas.add(lemma)
    return sorted(lemmas)


# TEST_WORDS = [
#     "dog", "run", "happy", "take", "go", "be",
#     "car", "love", "think", "beautiful", "quickly",
#     "water", "fire", "eat", "see", "child",
#     "good", "bad", "big", "small", "take_over",
#     "bank", "light", "break", "head", "line",
#     "give", "make", "come", "know", "get",
# ]

# 全量单词（从 dict/index.* 源文件提取）
TEST_WORDS = _load_all_lemmas()

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
    assert not diffs, f"单词 '{word}' 文件端与数据库端不一致:\n" + "\n".join(
        f"  - {d}" for d in diffs
    )


@pytest.mark.parametrize("word,pos", TEST_WORD_POS)
def test_word_pos_lookup_consistency(word, pos, file_db, db_db):
    """指定词性，对比单义词性查询结果。"""
    file_results = file_db.lookup(word, pos)
    db_results = db_db.lookup(word, pos)
    diffs = compare_lookup_results(word, file_results, db_results, file_db)
    assert not diffs, f"单词 '{word}' [{pos}] 文件端与数据库端不一致:\n" + "\n".join(
        f"  - {d}" for d in diffs
    )
