#!/usr/bin/env python3
"""分析 87 个失败用例的具体根因。"""

import re, sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import DICT_DIR, WordNetDB
from tests.db_backend import DbWordNetDB
from tests.compare_utils import compare_lookup_results

DB_PATH = Path(__file__).parent.parent / "db" / "wn.db"

FAILING_WORDS = [
    "abounding",
    "abundant",
    "aforethought",
    "afoul",
    "akimbo",
    "backward",
    "britain",
    "centigrade",
    "combining_form",
    "couchant",
    "crooked",
    "ddc",
    "ddi",
    "designate",
    "didanosine",
    "dideoxycytosine",
    "dideoxyinosine",
    "dormant",
    "down",
    "downward",
    "earth",
    "elect",
    "erect",
    "extraordinaire",
    "extraordinary",
    "fahrenheit",
    "feathered",
    "flighted",
    "forward",
    "foul",
    "fouled",
    "full-face",
    "galore",
    "gardant",
    "globe",
    "great_britain",
    "guardant",
    "heraldry",
    "immemorial",
    "important",
    "in-chief",
    "inclined",
    "incoming",
    "junior",
    "k",
    "kb",
    "kib",
    "kibibyte",
    "kilobyte",
    "major",
    "many",
    "minor",
    "moon",
    "of_import",
    "old",
    "passant",
    "planned",
    "plotted",
    "powerful",
    "premeditated",
    "proper",
    "ramp",
    "rampant",
    "rearing",
    "redux",
    "regardant",
    "regency",
    "regent",
    "revived",
    "salient",
    "senior",
    "sleeping",
    "specific",
    "statant",
    "sun",
    "tangled",
    "u.k.",
    "uk",
    "unerect",
    "united_kingdom",
    "united_kingdom_of_great_britain_and_northern_ireland",
    "upright",
    "vertical",
    "volant",
    "winged",
    "world",
    "zalcitabine",
]

print("加载 ...", file=sys.stderr)
file_db = WordNetDB(DICT_DIR)
db_db = DbWordNetDB(DB_PATH)

cats = defaultdict(list)

for word in FAILING_WORDS:
    fr = file_db.lookup(word)
    dr = db_db.lookup(word)
    diffs = compare_lookup_results(word, fr, dr, file_db)
    for d in diffs:
        if ".words:" in d:
            cats["words"].append((word, d))
        elif ".pointers:" in d:
            cats["pointers"].append((word, d))
        elif ".current_word." in d:
            cats["current_word"].append((word, d))
        elif ".pos_name:" in d:
            cats["pos_name"].append((word, d))
        elif ".lex_filenum:" in d:
            cats["lex_filenum"].append((word, d))
        else:
            cats["other"].append((word, d))

print(f"\n{'='*80}")
for cat, items in sorted(cats.items(), key=lambda x: -len(x[1])):
    words = sorted(set(w for w, _ in items))
    print(f"\n[{cat}] {len(words)}个单词:")
    for w in words:
        print(f"  {w}")
    print()

# ── words 深入：取几个样本，对比原始数据 ──
print(f"\n{'='*80}")
print("words_mismatch 深入分析 (每个 synset 的 data 行 vs index.sense)")

analyzed_sids = set()
for word, diff in cats["words"][:10]:
    sid = diff.split("/")[0]
    if sid in analyzed_sids:
        continue
    analyzed_sids.add(sid)

    syn = file_db.synsets.get(sid)
    if not syn:
        continue
    f_words = [(w, lid) for w, lid in syn.words]
    d_words = db_db._synset_words.get(sid, [])
    only_file = set(f_words) - set(d_words)

    print(f"\n  synset: {sid}  ss_type={syn.ss_type}")
    print(f"  data line words: {f_words}")
    print(f"  DB sense words:   {d_words}")
    print(f"  仅在文件: {only_file}")

    for w_extra, lid_extra in only_file:
        # 构造可能的 sense_key 前缀查找
        # 在 index.sense 中搜索相关条目
        offset = sid[:-1]
        pos_char = sid[-1]
        ss_code = {"n": 1, "v": 2, "a": 3, "r": 4, "s": 5}.get(pos_char, 1)
        prefix = f"{w_extra}%{ss_code}:"
        found = False
        with open(DICT_DIR / "index.sense", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == offset:
                    sk = parts[0]
                    if sk.lower().startswith(prefix.lower()):
                        # 解析 lex_id
                        m = re.search(r"%\d+:\d+:(\d+)", sk)
                        sk_lex_id = int(m.group(1)) if m else -1
                        print(f"    index.sense 中找到: {sk} (lex_id={sk_lex_id})")
                        found = True
        if not found:
            print(f"    index.sense 中无匹配: offset={offset}, search='{prefix}'")

# ── pointers 深入 ──
if cats["pointers"]:
    print(f"\n{'='*80}")
    print("pointers 深入分析")
    for word, diff in cats["pointers"][:10]:
        print(f"\n  {word}: {diff}")
