#!/usr/bin/env python3
"""分析 import_wn.py parse_data_file 的指针校正逻辑错误。"""

import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
from main import DICT_DIR, WordNetDB, POINTER_DESC

# ── Step 1: 构建 offset → 出现在哪些 POS 文件 ──
offset_pos_files = defaultdict(set)
for fname, pos_char in [
    ("data.noun", "n"),
    ("data.verb", "v"),
    ("data.adj", "a"),
    ("data.adv", "r"),
]:
    with open(DICT_DIR / fname, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("  ") or line.startswith("This"):
                continue
            head, _, gloss = line.partition(" | ")
            if not gloss:
                continue
            parts = head.split()
            if len(parts) < 4 or not parts[0].isdigit() or len(parts[0]) != 8:
                continue
            offset_pos_files[parts[0]].add(parts[2])

# ── Step 2: 扫描 data.adj 所有指针，找出被错误覆盖的 ──
errors = []
with open(DICT_DIR / "data.adj", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("  ") or line.startswith("This"):
            continue
        head, _, gloss = line.partition(" | ")
        if not gloss:
            continue
        parts = head.split()
        if len(parts) < 4 or not parts[0].isdigit() or len(parts[0]) != 8:
            continue
        offset = parts[0]
        ss_type = parts[2]
        w_cnt = int(parts[3], 16)
        idx = 4 + w_cnt * 2
        p_cnt = int(parts[idx])
        idx += 1
        for _ in range(p_cnt):
            symbol = parts[idx]
            t_offset = parts[idx + 1]
            t_pos = parts[idx + 2]
            idx += 4

            # 只看 t_pos 不是 a/s 的（即 n/v/r）
            if t_pos in ("a", "s"):
                continue

            # offset 必须同时存在于 data.adj 和 data.{t_pos}
            offset_files = offset_pos_files.get(t_offset, set())
            has_adj = bool(offset_files & {"a", "s"})
            has_claimed = t_pos in offset_files

            if has_adj and has_claimed:
                adj_types = offset_files & {"a", "s"}
                errors.append(
                    {
                        "source_synset": f"{offset}{ss_type}",
                        "symbol": symbol,
                        "original_target": f"{t_offset}{t_pos}",
                        "import_changed_to": f"{t_offset}{list(adj_types)[0]}",
                    }
                )

# ── Step 3: 加载 WordNetDB 获取语义信息 ──
db = WordNetDB(DICT_DIR)

print("=" * 80)
print("import_wn.py parse_data_file 指针校正逻辑错误分析")
print("=" * 80)
print()
print("BUG 位置: import_wn.py 第 286-324 行 parse_data_file()")
print()
print("逻辑:")
print("  1. 扫描 data.adj 所有行，建立 offset → ss_type 映射")
print("     offset_ss_map[offset] = ss_type  # 'a' 或 's'")
print()
print("  2. 重新解析 data.adj，对每个 pointer 用映射覆盖 t_pos:")
print("     actual_pos = offset_ss_map.get(t_offset, t_pos)")
print("     target_synset_id = t_offset + actual_pos")
print()
print("  3. BUG: 当同一个 offset 同时存在于 data.adj 和 data.noun/data.verb")
print("     时，原始 t_pos='n'/'v' 是正确的（指向名词/动词 synset），")
print("     但导入程序用 adj 内部的 ss_type='a'/'s' 覆盖了它。")
print()
print(f"  共发现 {len(errors)} 条被错误覆盖的指针")
print()

# 按符号统计
by_symbol = defaultdict(int)
for e in errors:
    by_symbol[e["symbol"]] += 1
print("按指针符号分布:")
for sym, cnt in sorted(by_symbol.items(), key=lambda x: -x[1]):
    desc = POINTER_DESC.get(sym, sym)
    print(f"  {sym} ({desc}): {cnt} 条")

# ── Step 4: 逐条详情 ──
print()
print("=" * 80)
print("逐条详情")
print("=" * 80)

for i, e in enumerate(errors):
    src = db.synsets.get(e["source_synset"])
    src_name = src.word_list if src else "?"
    orig_tgt = db.synsets.get(e["original_target"])
    changed_tgt = db.synsets.get(e["import_changed_to"])

    desc = POINTER_DESC.get(e["symbol"], e["symbol"])
    print(f"\n[{i+1}] symbol={e['symbol']} ({desc})")
    print(f"    source synset: {e['source_synset']}  words={src_name}")
    if src:
        print(f"    source gloss:  {src.gloss[:100]}")

    print(f"    raw t_pos = '{e['original_target'][-1]}'")
    print(
        f"    原始 target:   {e['original_target']}  {'[EXISTS]' if orig_tgt else '[MISSING]'}"
    )
    if orig_tgt:
        print(f"      -> words: {orig_tgt.word_list}")
        print(f"      -> gloss: {orig_tgt.gloss[:100]}")
    else:
        print(f"      -> (synset 不存在)")

    print(
        f"    导入改成:      {e['import_changed_to']}  {'[EXISTS]' if changed_tgt else '[MISSING]'}"
    )
    if changed_tgt:
        print(f"      -> words: {changed_tgt.word_list}")
        print(f"      -> gloss: {changed_tgt.gloss[:100]}")
    else:
        print(f"      -> (synset 不存在)")
