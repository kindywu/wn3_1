#!/usr/bin/env python3
"""
直接校验 WordNet 3.1 源数据中的错误。
不从数据库读取，直接从 dict/ 源文件解析并验证。

验证三项:
  1. 词级指针无法解析到 sense（data.* 中的 w_num 对应的 (synset_id, lex_id) 在 index.sense 中不存在）
  2. sentidx.vrb 中 sense_key 在 index.sense 中不存在
  3. cntlist 中 sense_key 在 index.sense 中不存在
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

DICT_DIR = Path(__file__).parent.parent / "dict"

POS_TO_FILE = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}
SS_TYPE_FROM_CODE = {1: "n", 2: "v", 3: "a", 4: "r", 5: "s"}


def load_sense_index(filepath: Path) -> tuple:
    """从 index.sense 构建:
    - sid_lex_map: (synset_id, lex_id) -> [sense_keys]
    - sense_keys: set of all sense_key
    - total: count
    """
    sid_lex_map = defaultdict(list)
    sense_keys = set()
    total = 0

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue

            sense_key = parts[0]
            offset = parts[1]
            sense_keys.add(sense_key)

            m = re.search(r"%(\d+)", sense_key)
            if m:
                ss_type_num = int(m.group(1))
                pos = SS_TYPE_FROM_CODE.get(ss_type_num, "n")
            else:
                pos = "n"

            synset_id = f"{offset}{pos}"
            total += 1

            lex_id = 0
            m2 = re.search(r"%(\d+):(\d+):(\d+)", sense_key)
            if m2:
                lex_id = int(m2.group(3))

            sid_lex_map[(synset_id, lex_id)].append(sense_key)

    return sid_lex_map, sense_keys, total


def build_synset_set(dict_dir: Path) -> set:
    """从 data.* 文件构建所有有效 synset_id 的集合（用于 adj satellite 校正）"""
    synset_ids = set()
    for pos_code, fname in POS_TO_FILE.items():
        fpath = dict_dir / f"data.{fname}"
        if not fpath.exists():
            continue
        with open(fpath, "r", encoding="utf-8") as f:
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
                synset_ids.add(f"{parts[0]}{parts[2]}")
    return synset_ids


def verify_pointers(sid_lex_map: dict, dict_dir: Path):
    """验证 data.* 文件中的词级指针是否能解析到 index.sense 中的 sense 记录"""
    print("=" * 60)
    print("验证 1: 词级指针 -> sense 匹配")
    print("=" * 60)

    # 构建有效 synset_id 集合用于 adj satellite t_pos 校正
    valid_synsets = build_synset_set(dict_dir)
    print(f"  有效 synset 数: {len(valid_synsets)}")

    unresolved = []
    total_word_ptr = 0

    for pos_code, fname in POS_TO_FILE.items():
        fpath = dict_dir / f"data.{fname}"
        if not fpath.exists():
            print(f"  [跳过] {fpath} 不存在")
            continue

        with open(fpath, "r", encoding="utf-8") as f:
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

                idx = 4
                for _ in range(w_cnt):
                    idx += 2  # skip word + lex_id

                p_cnt = int(parts[idx])
                idx += 1
                for _ in range(p_cnt):
                    symbol = parts[idx]
                    t_offset = parts[idx + 1]
                    t_pos_raw = parts[idx + 2]
                    hex_str = parts[idx + 3]
                    src_w = int(hex_str[:2], 16) if len(hex_str) >= 4 else 0
                    tgt_w = int(hex_str[2:4], 16) if len(hex_str) >= 4 else 0
                    idx += 4

                    source_synset_id = f"{offset}{ss_type}"

                    # 校正 target_synset_id 的 t_pos（与导入逻辑一致）
                    # grind 编译器对 adj 指针统一使用 t_pos='a'
                    # 如果 'a' 版本无效但 's' 版本有效，则使用 's'
                    raw_target_id = f"{t_offset}{t_pos_raw}"
                    if raw_target_id not in valid_synsets:
                        alt_id = f"{t_offset}s"
                        if alt_id in valid_synsets:
                            target_synset_id = alt_id
                        else:
                            target_synset_id = raw_target_id
                    else:
                        target_synset_id = raw_target_id

                    # source 方向
                    if src_w > 0:
                        total_word_ptr += 1
                        lex_id = src_w - 1
                        if (source_synset_id, lex_id) not in sid_lex_map:
                            unresolved.append(
                                ("source", symbol, source_synset_id, src_w, lex_id)
                            )

                    # target 方向
                    if tgt_w > 0:
                        total_word_ptr += 1
                        lex_id = tgt_w - 1
                        if (target_synset_id, lex_id) not in sid_lex_map:
                            unresolved.append(
                                (
                                    "target",
                                    symbol,
                                    target_synset_id,
                                    tgt_w,
                                    lex_id,
                                )
                            )

    print(f"  词级指针总数 (w_num>0, src+tgt): {total_word_ptr}")
    print(f"  无法解析: {len(unresolved)} 条")

    src_unresolved = [e for e in unresolved if e[0] == "source"]
    tgt_unresolved = [e for e in unresolved if e[0] == "target"]
    print(f"    source 方向: {len(src_unresolved)} 条")
    print(f"    target 方向: {len(tgt_unresolved)} 条")

    by_sym = defaultdict(lambda: {"source": 0, "target": 0})
    for direction, sym, *_ in unresolved:
        by_sym[sym][direction] += 1

    print(f"  按指针符号分布:")
    for sym in sorted(
        by_sym.keys(),
        key=lambda s: by_sym[s]["source"] + by_sym[s]["target"],
        reverse=True,
    ):
        s = by_sym[sym]["source"]
        t = by_sym[sym]["target"]
        print(f"    {sym}: source={s}, target={t}")

    print(f"\n  前 10 条示例:")
    for i, (direction, sym, syn_id, w_num, lex_id) in enumerate(unresolved[:10]):
        print(f"    {i+1}. {direction} {sym} {syn_id} w_num={w_num} lex_id={lex_id}")

    return unresolved


def verify_sentidx(sense_keys: set):
    """验证 sentidx.vrb 中的 sense_key 是否在 index.sense 中存在"""
    print(f"\n{'=' * 60}")
    print("验证 2: sentidx.vrb sense_key 匹配")
    print("=" * 60)

    fpath = DICT_DIR / "sentidx.vrb"
    if not fpath.exists():
        print(f"  [跳过] {fpath} 不存在")
        return []

    missing = []
    total = 0
    seen = set()
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                sense_key = parts[0]
                if sense_key not in seen:
                    seen.add(sense_key)
                    total += 1
                    if sense_key not in sense_keys:
                        missing.append(sense_key)

    print(f"  sentidx.vrb 唯一 sense_key: {len(seen)} (总行数含重复: 3420)")
    print(f"  无法匹配: {len(missing)} 条")
    for sk in missing:
        print(f"    {sk}")

    return missing


def verify_cntlist(sense_keys: set):
    """验证 cntlist 中的 sense_key 是否在 index.sense 中存在"""
    print(f"\n{'=' * 60}")
    print("验证 3: cntlist sense_key 匹配")
    print("=" * 60)

    fpath = DICT_DIR / "cntlist"
    if not fpath.exists():
        print(f"  [跳过] {fpath} 不存在")
        return []

    missing = []
    total = 0
    seen = set()
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            total += 1
            sense_key = parts[1]
            if sense_key not in seen:
                seen.add(sense_key)
            if sense_key not in sense_keys:
                missing.append(sense_key)

    print(f"  cntlist 总计条目: {total} (唯一 sense_key: {len(seen)})")
    print(f"  无法匹配: {len(missing)} 条")
    for sk in missing:
        print(f"    {sk}")

    return missing


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    sense_path = DICT_DIR / "index.sense"
    if not sense_path.exists():
        print(f"[错误] index.sense 不存在: {sense_path}")
        sys.exit(1)

    print("加载 index.sense ...")
    sid_lex_map, sense_keys, total_sense = load_sense_index(sense_path)
    print(
        f"  加载完成: {total_sense} 条 sense, {len(sid_lex_map)} 个 (synset_id,lex_id) 组合\n"
    )

    # 验证 1: 词级指针
    unresolved = verify_pointers(sid_lex_map, DICT_DIR)

    # 验证 2: sentidx.vrb
    missing_sentidx = verify_sentidx(sense_keys)

    # 验证 3: cntlist
    missing_cntlist = verify_cntlist(sense_keys)

    # 汇总
    print(f"\n{'=' * 60}")
    print("汇总")
    print("=" * 60)
    print(f"  1. 词级指针无法解析: {len(unresolved)} 条")
    print(f"  2. sentidx.vrb 无匹配: {len(missing_sentidx)} 条")
    print(f"  3. cntlist 无匹配:     {len(missing_cntlist)} 条")

    print(f"\n  日志报告值:")
    print(f"    词级指针无法解析: 66379 条 (src=33165, tgt=33214)")
    print(f"    sentidx.vrb 无匹配: 4 条")
    print(f"    cntlist 无匹配: 2080 条")

    # 详细对比
    src_cnt = sum(1 for e in unresolved if e[0] == "source")
    tgt_cnt = sum(1 for e in unresolved if e[0] == "target")
    diff = len(unresolved) - 66379
    print(f"\n  差异分析:")
    print(f"    脚本: total={len(unresolved)} (src={src_cnt}, tgt={tgt_cnt})")
    print(f"    日志: total=66379 (src=33165, tgt=33214)")


if __name__ == "__main__":
    main()
