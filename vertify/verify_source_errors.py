#!/usr/bin/env python3
"""
逐条校验 WordNet 3.1 源数据错误，与导入日志双向比对。

直接从 dict/ 源文件解析，与 db/ 下的两份日志逐条核对：
  1. import_wn3.1_unresolved_pointers.log — 词级指针无法解析
  2. import_wn3.1.log 中的 sentidx / cntlist 条目

输出：
  - 日志有 & 源数据确认: 交集，两边一致
  - 日志有 & 源数据未发现: 日志报了但源数据验证没找到
  - 源数据有 & 日志未报: 源数据发现了问题但日志没记录
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

DICT_DIR = Path(__file__).parent.parent / "dict"
DB_DIR = Path(__file__).parent.parent / "db"

POS_TO_FILE = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}
SS_TYPE_FROM_CODE = {1: "n", 2: "v", 3: "a", 4: "r", 5: "s"}


# ── 解析日志文件 ──


def parse_unresolved_pointers_log(filepath: Path) -> set:
    """解析 unresolved_pointers.log，返回 {(direction, symbol, synset_id, w_num, lex_id)}"""
    entries = set()
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("="):
                continue
            if (
                line.startswith("总计")
                or line.startswith("格式")
                or line.startswith("原因")
            ):
                continue
            parts = line.split("\t")
            if len(parts) == 5:
                direction, symbol, syn_id, w_num, lex_id = parts
                entries.add((direction, symbol, syn_id, int(w_num), int(lex_id)))
    return entries


def parse_sentidx_from_main_log(filepath: Path) -> set:
    """从主日志中解析 sentidx.vrb 无匹配的 sense_key 列表"""
    entries = set()
    in_section = False
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "--- 2. sentidx.vrb" in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("--- 3.") or line.startswith("===="):
                    break
                if line and not line.startswith("---") and not line.startswith("共"):
                    sk = line.strip()
                    if (
                        sk
                        and not sk.startswith("sentidx")
                        and not sk.startswith("详细条目")
                    ):
                        entries.add(sk)
    return entries


def parse_cntlist_from_main_log(filepath: Path) -> set:
    """从主日志中解析 cntlist 无匹配的 sense_key 列表"""
    entries = set()
    in_section = False
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "--- 3. cntlist" in line:
                in_section = True
                continue
            if in_section:
                if line.startswith("===="):
                    break
                if line and not line.startswith("---") and not line.startswith("共"):
                    sk = line.strip()
                    if sk and not sk.startswith("cntlist"):
                        entries.add(sk)
    return entries


# ── 从源数据构建索引 ──


def load_sense_index(filepath: Path) -> tuple:
    """从 index.sense 构建 (synset_id, lex_id) 集合 和 sense_key 集合"""
    sid_lex_set = set()
    sense_keys = set()

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

            lex_id = 0
            m2 = re.search(r"%(\d+):(\d+):(\d+)", sense_key)
            if m2:
                lex_id = int(m2.group(3))

            sid_lex_set.add((synset_id, lex_id))

    return sid_lex_set, sense_keys


def build_synset_set(dict_dir: Path) -> set:
    """从 data.* 文件构建所有有效 synset_id 的集合"""
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


def find_unresolved_from_source(sid_lex_set: set, dict_dir: Path) -> set:
    """从 data.* 源文件找出所有无法解析的词级指针"""
    valid_synsets = build_synset_set(dict_dir)
    unresolved = set()

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

                offset = parts[0]
                ss_type = parts[2]
                w_cnt = int(parts[3], 16)

                idx = 4
                for _ in range(w_cnt):
                    idx += 2

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

                    raw_target_id = f"{t_offset}{t_pos_raw}"
                    if raw_target_id not in valid_synsets:
                        alt_id = f"{t_offset}s"
                        if alt_id in valid_synsets:
                            target_synset_id = alt_id
                        else:
                            target_synset_id = raw_target_id
                    else:
                        target_synset_id = raw_target_id

                    if src_w > 0:
                        lex_id = src_w - 1
                        if (source_synset_id, lex_id) not in sid_lex_set:
                            unresolved.add(
                                ("source", symbol, source_synset_id, src_w, lex_id)
                            )

                    if tgt_w > 0:
                        lex_id = tgt_w - 1
                        if (target_synset_id, lex_id) not in sid_lex_set:
                            unresolved.add(
                                ("target", symbol, target_synset_id, tgt_w, lex_id)
                            )

    return unresolved


def find_missing_sentidx_from_source(sense_keys: set) -> set:
    """从 sentidx.vrb 源文件找出所有不在 index.sense 中的 sense_key"""
    missing = set()
    fpath = DICT_DIR / "sentidx.vrb"
    if not fpath.exists():
        return missing

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                sense_key = parts[0]
                if sense_key not in sense_keys:
                    missing.add(sense_key)

    return missing


def find_missing_cntlist_from_source(sense_keys: set) -> set:
    """从 cntlist 源文件找出所有不在 index.sense 中的 sense_key"""
    missing = set()
    fpath = DICT_DIR / "cntlist"
    if not fpath.exists():
        return missing

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            sense_key = parts[1]
            if sense_key not in sense_keys:
                missing.add(sense_key)

    return missing


# ── 双向对比 ──


def compare_sets(name: str, log_set: set, source_set: set, sort_key=None):
    """逐条对比日志和源数据，打印详细差异"""
    print(f"\n{'─' * 60}")
    print(f"逐条对比: {name}")
    print(f"{'─' * 60}")
    print(f"  日志记录: {len(log_set)} 条")
    print(f"  源数据发现: {len(source_set)} 条")

    both = log_set & source_set
    only_in_log = log_set - source_set
    only_in_source = source_set - log_set

    print(f"  一致 (交集): {len(both)} 条")
    print(f"  日志有 & 源数据无: {len(only_in_log)} 条")
    print(f"  源数据有 & 日志无: {len(only_in_source)} 条")

    if only_in_log:
        print(f"\n  【差异】日志报告但源数据未发现 ({len(only_in_log)} 条):")
        items = sorted(only_in_log, key=sort_key) if sort_key else sorted(only_in_log)
        for item in items[:30]:
            print(f"    {item}")
        if len(only_in_log) > 30:
            print(f"    ... (共 {len(only_in_log)} 条)")

    if only_in_source:
        print(f"\n  【差异】源数据发现但日志未报告 ({len(only_in_source)} 条):")
        items = (
            sorted(only_in_source, key=sort_key) if sort_key else sorted(only_in_source)
        )
        for item in items[:30]:
            print(f"    {item}")
        if len(only_in_source) > 30:
            print(f"    ... (共 {len(only_in_source)} 条)")

    if not only_in_log and not only_in_source:
        print(f"\n  ✓ 完全一致")

    return both, only_in_log, only_in_source


# ── 主流程 ──


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # 加载源数据索引
    sense_path = DICT_DIR / "index.sense"
    if not sense_path.exists():
        print(f"[错误] index.sense 不存在: {sense_path}")
        sys.exit(1)

    print("加载 index.sense ...")
    sid_lex_set, sense_keys = load_sense_index(sense_path)
    print(
        f"  {len(sid_lex_set)} 个 (synset_id, lex_id) 组合, {len(sense_keys)} 个 sense_key\n"
    )

    # ── 验证 1: 词级指针 ──
    ptr_log_path = DB_DIR / "import_wn3.1_unresolved_pointers.log"
    if ptr_log_path.exists():
        print("解析 unresolved_pointers.log ...")
        log_ptr_entries = parse_unresolved_pointers_log(ptr_log_path)
        print(f"  日志记录: {len(log_ptr_entries)} 条")
    else:
        print(f"[警告] 日志文件不存在: {ptr_log_path}")
        log_ptr_entries = set()

    print("从源数据查找无法解析的词级指针 ...")
    source_ptr_unresolved = find_unresolved_from_source(sid_lex_set, DICT_DIR)
    print(f"  源数据发现: {len(source_ptr_unresolved)} 条")

    compare_sets("词级指针无法解析", log_ptr_entries, source_ptr_unresolved)

    # ── 验证 2: sentidx.vrb ──
    main_log_path = DB_DIR / "import_wn3.1.log"
    if main_log_path.exists():
        print("\n解析 import_wn3.1.log 中的 sentidx 条目 ...")
        log_sentidx = parse_sentidx_from_main_log(main_log_path)
        print(f"  日志记录: {len(log_sentidx)} 条")
    else:
        log_sentidx = set()

    source_sentidx_missing = find_missing_sentidx_from_source(sense_keys)
    compare_sets("sentidx.vrb 无匹配 sense_key", log_sentidx, source_sentidx_missing)

    # ── 验证 3: cntlist ──
    if main_log_path.exists():
        print("\n解析 import_wn3.1.log 中的 cntlist 条目 ...")
        log_cntlist = parse_cntlist_from_main_log(main_log_path)
        print(f"  日志记录: {len(log_cntlist)} 条")
    else:
        log_cntlist = set()

    source_cntlist_missing = find_missing_cntlist_from_source(sense_keys)
    compare_sets("cntlist 无匹配 sense_key", log_cntlist, source_cntlist_missing)

    # ── 最终汇总 ──
    both_ptr, only_log_ptr, only_src_ptr = (
        log_ptr_entries & source_ptr_unresolved,
        log_ptr_entries - source_ptr_unresolved,
        source_ptr_unresolved - log_ptr_entries,
    )
    both_si, only_log_si, only_src_si = (
        log_sentidx & source_sentidx_missing,
        log_sentidx - source_sentidx_missing,
        source_sentidx_missing - log_sentidx,
    )
    both_cl, only_log_cl, only_src_cl = (
        log_cntlist & source_cntlist_missing,
        log_cntlist - source_cntlist_missing,
        source_cntlist_missing - log_cntlist,
    )

    print(f"\n{'=' * 60}")
    print("最终汇总")
    print("=" * 60)
    print(f"  1. 词级指针:")
    print(f"     日志有 & 源数据确认: {len(both_ptr)} 条")
    print(f"     日志有 & 源数据未确认: {len(only_log_ptr)} 条")
    print(f"     源数据有 & 日志未报: {len(only_src_ptr)} 条")
    print(f"  2. sentidx.vrb:")
    print(
        f"     一致: {len(both_si)}, 仅日志: {len(only_log_si)}, 仅源数据: {len(only_src_si)}"
    )
    print(f"  3. cntlist:")
    print(
        f"     一致: {len(both_cl)}, 仅日志: {len(only_log_cl)}, 仅源数据: {len(only_src_cl)}"
    )

    all_ok = len(only_log_ptr) == 0 and len(only_log_si) == 0 and len(only_log_cl) == 0
    if (
        all_ok
        and len(only_src_ptr) == 0
        and len(only_src_si) == 0
        and len(only_src_cl) == 0
    ):
        print(f"\n  ✓ 所有条目完全一致")
    elif all_ok:
        print(
            f"\n  ⚠ 日志报告的全部条目均被源数据验证确认，但源数据额外发现了一些日志未报的条目"
        )


if __name__ == "__main__":
    main()
