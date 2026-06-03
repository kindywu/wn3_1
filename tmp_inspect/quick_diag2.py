#!/usr/bin/env python3
"""第二轮: 聚焦 other 类别，以及逐条显示详细差异。"""

import sys
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

# 收集完整差异文本（不做分类）
print("=" * 80)
print("逐词差异详情")
print("=" * 80)

for word in FAILING_WORDS[:40]:  # 只看前40个
    fr = file_db.lookup(word)
    dr = db_db.lookup(word)
    diffs = compare_lookup_results(word, fr, dr, file_db)
    if diffs:
        print(f"\n─── {word} ({len(diffs)} 差异) ───")
        for d in diffs:
            print(f"  {d}")
