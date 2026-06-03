#!/usr/bin/env python3
"""诊断全量对比测试的 87 个失败用例，分类根因。"""

import sys
from pathlib import Path
from collections import defaultdict, Counter

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import DICT_DIR, WordNetDB
from tests.db_backend import DbWordNetDB
from tests.compare_utils import compare_lookup_results

DB_PATH = Path(__file__).parent.parent / "db" / "wn.db"

# 加载 test_compare.py 的 TEST_WORDS
sys.path.insert(0, str(Path(__file__).parent.parent / "tests"))
from test_compare import TEST_WORDS

print("加载 file_db ...", file=sys.stderr)
file_db = WordNetDB(DICT_DIR)
print("加载 db_db ...", file=sys.stderr)
db_db = DbWordNetDB(DB_PATH)

# ── 逐词比较并分类 ──
error_categories = defaultdict(list)
error_details = []

for word in TEST_WORDS:
    file_results = file_db.lookup(word)
    db_results = db_db.lookup(word)
    diffs = compare_lookup_results(word, file_results, db_results, file_db)
    if not diffs:
        continue

    # 分类
    for d in diffs:
        if ".words:" in d:
            # 解析出差异
            error_categories["words_mismatch"].append(word)
        elif ".pointers:" in d and "仅文件" in d:
            error_categories["pointers_file_only"].append(word)
        elif ".pointers:" in d and "仅DB" in d:
            error_categories["pointers_db_only"].append(word)
        elif ".current_word." in d:
            error_categories["current_word"].append(word)
        elif ".gloss:" in d:
            error_categories["gloss"].append(word)
        elif ".lex_filenum:" in d:
            error_categories["lex_filenum"].append(word)
        elif ".pos_name:" in d:
            error_categories["pos_name"].append(word)
        elif ".sense_key" in d:
            error_categories["sense_key"].append(word)
        elif ".lex_id" in d:
            error_categories["lex_id"].append(word)
        elif ".frequency" in d:
            error_categories["frequency"].append(word)
        elif ".frame" in d:
            error_categories["frames"].append(word)
        elif ".example" in d:
            error_categories["examples"].append(word)
        else:
            error_categories["other"].append(word)

    error_details.append((word, diffs))

# ── 输出汇总 ──
print("=" * 80)
print("失败用例分类汇总")
print("=" * 80)
total_failing = len(set(w for w, _ in error_details))
print(f"总计 {total_failing} 个单词有差异\n")

for cat, words in sorted(error_categories.items(), key=lambda x: -len(set(x[1]))):
    unique = sorted(set(words))
    print(f"[{cat}] {len(unique)} 个单词")
    for w in unique[:10]:
        print(f"  - {w}")
    if len(unique) > 10:
        print(f"  ... 还有 {len(unique) - 10} 个")

# ── 深入分析 words_mismatch ──
print()
print("=" * 80)
print("words_mismatch 深入分析")
print("=" * 80)

words_errors = [(w, d) for w, d in error_details if any(".words:" in dd for dd in d)]
for word, diffs in words_errors[:15]:
    print(f"\n--- {word} ---")
    for d in diffs:
        if ".words:" in d:
            # 提取 synset_id
            sid = d.split("/")[0]
            # 从原始数据确认
            src_syn = file_db.synsets.get(sid)
            if src_syn:
                print(f"  synset: {sid}  ss_type={src_syn.ss_type}")
                print(f"  file words: {[(w, lid) for w, lid in src_syn.words]}")
            db_words = db_db._synset_words.get(sid, [])
            print(f"  db   words: {db_words}")

            # 检查 index.sense
            print(f"  差异分析:")
            f_set = {(w, lid) for w, lid in src_syn.words} if src_syn else set()
            d_set = set(db_words)
            extra_in_file = f_set - d_set
            extra_in_db = d_set - f_set
            if extra_in_file:
                print(f"    仅在文件: {extra_in_file}")
                for w_extra, lid_extra in extra_in_file:
                    # 检查 data 文件和 index.sense
                    print(
                        f"      word='{w_extra}' lex_id={lid_extra} — 检查是否是 ghost word"
                    )
            if extra_in_db:
                print(f"    仅在DB:   {extra_in_db}")
