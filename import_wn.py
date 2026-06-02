#!/usr/bin/env python3
"""
WordNet 字典导入工具
从 asset/ 目录读取 wn*.dict.tar.gz 压缩包，解压到 dict/，导入到 SQLite 数据库 db/wn.db
支持增量导入（通过 import_meta 表追踪版本）
"""

import sqlite3
import tarfile
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Iterator, Tuple, List, Dict

# ── 配置 ──
ASSET_DIR = Path(__file__).parent / "asset"
DICT_DIR = Path(__file__).parent / "dict"
DB_DIR = Path(__file__).parent / "db"
DB_PATH = DB_DIR / "wn.db"
LOG_DIR = DB_DIR

POS_TO_FILE = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}
POS_FILES = list(POS_TO_FILE.keys())

SS_TYPE_CODE = {"n": 1, "v": 2, "a": 3, "r": 4, "s": 5}
SS_TYPE_FROM_CODE = {1: "n", 2: "v", 3: "a", 4: "r", 5: "s"}

BATCH_SIZE = 5000

# ── SQL DDL ──
CREATE_TABLES_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS synset (
    synset_id   TEXT NOT NULL PRIMARY KEY,
    version     TEXT NOT NULL,
    offset      TEXT NOT NULL,
    pos         TEXT NOT NULL CHECK(pos IN ('n','v','a','r','s')),
    lex_filenum INTEGER NOT NULL,
    ss_type     TEXT NOT NULL CHECK(ss_type IN ('n','v','a','r','s')),
    gloss       TEXT NOT NULL,
    word_count  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS lexical_entry (
    entry_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    lemma               TEXT NOT NULL,
    pos                 TEXT NOT NULL CHECK(pos IN ('n','v','a','r')),
    version             TEXT NOT NULL,
    synset_count        INTEGER NOT NULL,
    tagged_sense_count  INTEGER NOT NULL,
    pointer_symbols     TEXT NOT NULL DEFAULT '',
    UNIQUE(lemma, pos, version)
);

CREATE TABLE IF NOT EXISTS sense (
    sense_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    synset_id       TEXT NOT NULL,
    entry_id        INTEGER NOT NULL,
    sense_key       TEXT NOT NULL,
    sense_number    INTEGER NOT NULL,
    tag_cnt         INTEGER NOT NULL DEFAULT 0,
    lex_id          INTEGER NOT NULL DEFAULT 0,
    version         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pointer (
    pointer_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol              TEXT NOT NULL,
    source_synset_id    TEXT NOT NULL,
    target_synset_id    TEXT NOT NULL,
    source_sense_id     INTEGER,
    target_sense_id     INTEGER,
    source_w_num        INTEGER NOT NULL DEFAULT 0,
    target_w_num        INTEGER NOT NULL DEFAULT 0,
    version             TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS syntactic_frame (
    frame_number    INTEGER PRIMARY KEY,
    frame_text      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sense_frame (
    sense_id        INTEGER NOT NULL,
    frame_number    INTEGER NOT NULL,
    version         TEXT NOT NULL,
    PRIMARY KEY (sense_id, frame_number)
);

CREATE TABLE IF NOT EXISTS example_sentence (
    sentence_number INTEGER PRIMARY KEY,
    sentence_text   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sense_example (
    sense_id        INTEGER NOT NULL,
    sentence_number INTEGER NOT NULL,
    version         TEXT NOT NULL,
    PRIMARY KEY (sense_id, sentence_number)
);

CREATE TABLE IF NOT EXISTS morph_exception (
    exception_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pos             TEXT NOT NULL CHECK(pos IN ('n','v','a','r')),
    surface_form    TEXT NOT NULL,
    base_form       TEXT NOT NULL,
    version         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sense_frequency (
    freq_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sense_id    INTEGER NOT NULL,
    count       INTEGER NOT NULL,
    rank        INTEGER NOT NULL,
    version     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_meta (
    version         TEXT PRIMARY KEY,
    source_file     TEXT NOT NULL,
    synset_count    INTEGER NOT NULL DEFAULT 0,
    pointer_count   INTEGER NOT NULL DEFAULT 0,
    sense_count     INTEGER NOT NULL DEFAULT 0,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    log_path        TEXT,
    error_summary   TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_synset_version ON synset(version);
CREATE INDEX IF NOT EXISTS idx_entry_lemma ON lexical_entry(lemma, pos, version);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sense_key ON sense(sense_key, version);
CREATE INDEX IF NOT EXISTS idx_sense_synset ON sense(synset_id);
CREATE INDEX IF NOT EXISTS idx_sense_entry ON sense(entry_id);
CREATE INDEX IF NOT EXISTS idx_pointer_source ON pointer(source_synset_id);
CREATE INDEX IF NOT EXISTS idx_pointer_target ON pointer(target_synset_id);
CREATE INDEX IF NOT EXISTS idx_pointer_symbol ON pointer(symbol);
CREATE INDEX IF NOT EXISTS idx_exc_surface ON morph_exception(surface_form, pos);
CREATE INDEX IF NOT EXISTS idx_exc_base ON morph_exception(base_form, pos);
CREATE INDEX IF NOT EXISTS idx_freq_sense ON sense_frequency(sense_id);
CREATE INDEX IF NOT EXISTS idx_freq_rank ON sense_frequency(rank);
"""

# ── 解压模块 ──


def find_archives() -> List[Path]:
    """扫描 asset/ 目录，返回所有 wn*.dict.tar.gz 文件路径。"""
    if not ASSET_DIR.exists():
        print(f"[错误] asset 目录不存在: {ASSET_DIR}")
        sys.exit(1)
    archives = sorted(ASSET_DIR.glob("wn*.dict.tar.gz"))
    if not archives:
        print(f"[错误] 未在 {ASSET_DIR} 中找到 wn*.dict.tar.gz 文件")
        sys.exit(1)
    return archives


def parse_version(archive_path: Path) -> str:
    """从文件名提取版本号。如 wn3.1.dict.tar.gz -> '3.1'"""
    name = archive_path.name
    m = re.search(r"wn(\d+\.\d+)\.", name)
    if not m:
        raise ValueError(f"无法从文件名提取版本号: {name}")
    return m.group(1)


def extract_archive(archive_path: Path) -> Path:
    """解压 tar.gz 到 dict/ 目录，返回解压后的 dict/ 路径。"""
    version = parse_version(archive_path)
    print(f"\n[解压] {archive_path.name} (版本 {version})")

    if DICT_DIR.exists():
        for item in DICT_DIR.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
    DICT_DIR.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        tar.extractall(path=DICT_DIR.parent, filter="data")

    required = [
        "data.noun",
        "data.verb",
        "data.adj",
        "data.adv",
        "index.noun",
        "index.verb",
        "index.adj",
        "index.adv",
        "index.sense",
    ]
    for fname in required:
        if not (DICT_DIR / fname).exists():
            raise FileNotFoundError(f"解压后缺少关键文件: {fname}")

    print(f"  解压完成 -> {DICT_DIR}")
    return DICT_DIR


# ── 解析器模块 ──


def _parse_data_lines(filepath: Path, pos: str) -> Iterator[Tuple[Dict, List[Dict]]]:
    """解析 data.* 文件的核心逻辑，逐行 yield (synset_row, [pointer_rows...])"""
    skipped = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("  ") or line.startswith("This"):
                continue

            head, _, gloss = line.partition(" | ")
            if not gloss:
                skipped += 1
                continue

            parts = head.split()
            # 格式验证: 第一个字段必须是 8 位数字 (offset)
            if len(parts) < 4 or not parts[0].isdigit() or len(parts[0]) != 8:
                skipped += 1
                continue

            offset = parts[0]
            lex_filenum = int(parts[1])
            ss_type = parts[2]
            w_cnt = int(parts[3], 16)

            idx = 4
            words = []
            for _ in range(w_cnt):
                word = parts[idx]
                lex_id = int(parts[idx + 1], 16)
                words.append((word, lex_id))
                idx += 2

            p_cnt = int(parts[idx])
            idx += 1
            pointers = []
            for _ in range(p_cnt):
                symbol = parts[idx]
                t_offset = parts[idx + 1]
                t_pos = parts[idx + 2]
                hex_str = parts[idx + 3]
                src_w = int(hex_str[:2], 16) if len(hex_str) >= 4 else 0
                tgt_w = int(hex_str[2:4], 16) if len(hex_str) >= 4 else 0
                pointers.append(
                    {
                        "symbol": symbol,
                        "target_synset_id": f"{t_offset}{t_pos}",
                        "source_w_num": src_w,
                        "target_w_num": tgt_w,
                    }
                )
                idx += 4

            frames = []
            if pos == "v":
                frame_match = re.findall(r"\+\s*(\d+)\s+(\d+)", head)
                for m in frame_match:
                    frames.append(int(m[0]))

            synset_row = {
                "synset_id": f"{offset}{ss_type}",
                "offset": offset,
                "pos": ss_type,
                "lex_filenum": lex_filenum,
                "ss_type": ss_type,
                "gloss": gloss.strip(),
                "word_count": w_cnt,
                "words": words,
                "frames": frames,
            }
            yield (synset_row, pointers)

    if skipped > 0:
        print(f"  [跳过] {filepath.name}: {skipped} 行 (许可证头/空白/非数据行)")


def parse_data_file(filepath: Path, pos: str) -> Iterator[Tuple[Dict, List[Dict]]]:
    """解析 data.* 文件，逐行 yield (synset_row, [pointer_rows...])。
    对于 data.adj，先构建 offset→ss_type 映射，用于校正 adj 指针的 t_pos
    （grind 编译器对 adj 指针统一使用 t_pos='a'，但实际 target 可能是 's' 型 satellite）"""
    if pos != "a":
        yield from _parse_data_lines(filepath, pos)
        return

    # data.adj: 先扫描所有行，构建 offset→ss_type 映射
    offset_ss_map: Dict[str, str] = {}
    with open(filepath, "r", encoding="utf-8") as f:
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
            offset_ss_map[parts[0]] = parts[2]  # offset -> ss_type (a or s)

    # 第二遍：解析并校正 pointer 的 target_synset_id
    for synset_row, pointers in _parse_data_lines(filepath, pos):
        corrected_pointers = []
        for p in pointers:
            # 提取 t_offset 和 t_pos，用映射校正 t_pos
            raw_id = p["target_synset_id"]
            t_offset = raw_id[:-1]
            t_pos = raw_id[-1]
            actual_pos = offset_ss_map.get(t_offset, t_pos)
            corrected_pointers.append(
                {
                    **p,
                    "target_synset_id": f"{t_offset}{actual_pos}",
                }
            )
        yield (synset_row, corrected_pointers)


def parse_index_file(filepath: Path, pos: str) -> Iterator[Dict]:
    """解析 index.* 文件，逐行 yield lexical_entry row"""
    skipped = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("  ") or line.startswith("This"):
                continue
            parts = line.split()
            if len(parts) < 3:
                skipped += 1
                continue
            # 格式验证: parts[1] 必须是有效词性, parts[2] 必须是数字
            if parts[1] not in ("n", "v", "a", "r"):
                skipped += 1
                continue
            if not parts[2].isdigit():
                skipped += 1
                continue

            lemma = parts[0]
            p_idx = 2
            synset_cnt = int(parts[p_idx])
            p_idx += 1
            ptr_cnt = int(parts[p_idx])
            p_idx += 1
            ptr_symbols = " ".join(parts[p_idx : p_idx + ptr_cnt])
            p_idx += ptr_cnt
            sense_cnt = int(parts[p_idx])
            p_idx += 1
            tagged_sense_cnt = int(parts[p_idx])
            p_idx += 1
            offsets = parts[p_idx : p_idx + synset_cnt]

            yield {
                "lemma": lemma,
                "pos": pos,
                "synset_count": synset_cnt,
                "tagged_sense_count": tagged_sense_cnt,
                "pointer_symbols": ptr_symbols,
                "offsets": offsets,
            }

    if skipped > 0:
        print(f"  [跳过] {filepath.name}: {skipped} 行 (许可证头/空白/非数据行)")


def parse_sense_index(filepath: Path) -> Iterator[Dict]:
    """解析 index.sense 文件，逐行 yield sense info"""
    skipped = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                skipped += 1
                continue

            sense_key = parts[0]
            offset = parts[1]
            sense_number = int(parts[2])
            tag_cnt = int(parts[3])

            # 从 sense_key 解析 pos: lemma%ss_type:...
            m = re.search(r"%(\d+)", sense_key)
            if m:
                ss_type_num = int(m.group(1))
                pos = SS_TYPE_FROM_CODE.get(ss_type_num, "n")
            else:
                pos = "n"
            # Adjective satellites (ss_type=5 -> pos='s') use pos='a' for lexical_entry lookup
            entry_pos = "a" if pos == "s" else pos

            yield {
                "sense_key": sense_key,
                "offset": offset,
                "pos": pos,
                "entry_pos": entry_pos,
                "sense_number": sense_number,
                "tag_cnt": tag_cnt,
            }

    if skipped > 0:
        print(f"  [注意] index.sense: 跳过 {skipped} 行格式不符")


def parse_exc(filepath: Path, pos: str) -> Iterator[Dict]:
    """解析 *.exc 文件，逐行 yield morph_exception row"""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                yield {
                    "pos": pos,
                    "surface_form": parts[0],
                    "base_form": parts[1],
                }


def parse_cntlist(filepath: Path) -> Iterator[Dict]:
    """解析 cntlist 文件，逐行 yield (sense_key, count, rank)"""
    skipped = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for rank, line in enumerate(f, 1):
            parts = line.strip().split()
            if len(parts) < 3:
                skipped += 1
                continue
            yield {
                "sense_key": parts[1],
                "count": int(parts[0]),
                "rank": rank,
            }
    if skipped:
        print(f"  [注意] cntlist: 跳过 {skipped} 行格式不符")


def parse_frames(filepath: Path) -> Iterator[Tuple[int, str]]:
    """解析 verb.Framestext，yield (frame_number, frame_text)"""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                yield (int(parts[0]), parts[1].strip())


def parse_sents(filepath: Path) -> Iterator[Tuple[int, str]]:
    """解析 sents.vrb，yield (sentence_number, text)"""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = re.match(r"(\d+)\s+(.*)", line)
            if m:
                yield (int(m.group(1)), m.group(2))


def parse_sentidx(filepath: Path) -> Iterator[Tuple[str, List[int]]]:
    """解析 sentidx.vrb，yield (sense_key, [sentence_numbers])"""
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                nums = [int(x.strip()) for x in parts[1].split(",")]
                yield (parts[0], nums)


# ── 导入器模块 ──


def get_conn() -> sqlite3.Connection:
    """获取数据库连接并执行 DDL"""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(CREATE_TABLES_SQL)
    conn.commit()
    return conn


def _delete_version_data(conn: sqlite3.Connection, version: str):
    """删除指定版本的所有数据（支持重新导入）"""
    cur = conn.cursor()
    tables = [
        "pointer",
        "sense_frame",
        "sense_example",
        "sense_frequency",
        "sense",
        "morph_exception",
        "lexical_entry",
        "synset",
    ]
    for t in tables:
        cur.execute(f"DELETE FROM {t} WHERE version=?", (version,))
    cur.execute("DELETE FROM import_meta WHERE version=?", (version,))
    conn.commit()
    print(f"  [清理] 已删除版本 {version} 的旧数据")


def import_synsets_and_pointers(
    conn: sqlite3.Connection, dict_dir: Path, version: str
) -> Tuple[int, int, Dict[str, List[int]]]:
    """导入 data.* 文件 -> synset + pointer 表。
    先导入所有 synset（确保 FK 存在），再批量导入 pointer。
    返回 (synset_count, pointer_count, synset_frames)"""
    synset_count = 0
    all_pointers: List[Tuple] = []
    synset_frames: Dict[str, List[int]] = {}
    synset_batch: List[Tuple] = []

    cur = conn.cursor()

    for pos in POS_FILES:
        data_path = dict_dir / f"data.{POS_TO_FILE[pos]}"
        if not data_path.exists():
            print(f"  [警告] 文件不存在: {data_path}")
            continue

        for synset_row, pointers in parse_data_file(data_path, pos):
            synset_id = synset_row["synset_id"]

            synset_batch.append(
                (
                    synset_id,
                    version,
                    synset_row["offset"],
                    synset_row["pos"],
                    synset_row["lex_filenum"],
                    synset_row["ss_type"],
                    synset_row["gloss"],
                    synset_row["word_count"],
                )
            )

            if synset_row["frames"]:
                synset_frames[synset_id] = synset_row["frames"]

            for p in pointers:
                all_pointers.append(
                    (
                        p["symbol"],
                        synset_id,
                        p["target_synset_id"],
                        p["source_w_num"],
                        p["target_w_num"],
                        version,
                    )
                )

            synset_count += 1

            if len(synset_batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT INTO synset(synset_id,version,offset,pos,lex_filenum,ss_type,gloss,word_count) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    synset_batch,
                )
                synset_batch.clear()

    if synset_batch:
        cur.executemany(
            "INSERT INTO synset(synset_id,version,offset,pos,lex_filenum,ss_type,gloss,word_count) "
            "VALUES(?,?,?,?,?,?,?,?)",
            synset_batch,
        )
    conn.commit()
    print(f"  synset: {synset_count} 行")

    # Phase 2: 批量导入所有 pointer（禁用 FK 以避免跨 pos 的目标 synset 尚不存在）
    pointer_count = len(all_pointers)
    cur.execute("PRAGMA foreign_keys=OFF")
    for i in range(0, len(all_pointers), BATCH_SIZE):
        batch = all_pointers[i : i + BATCH_SIZE]
        cur.executemany(
            "INSERT INTO pointer(symbol,source_synset_id,target_synset_id,"
            "source_w_num,target_w_num,version) VALUES(?,?,?,?,?,?)",
            batch,
        )
    # 校正 adj satellite 指针的 t_pos：grind 编译器对 adj 目标统一使用 t_pos='a'，
    # 但实际部分 synset 的 ss_type 为 's'（satellite）。将 t_pos='a' 但实际
    # synset_id 以 's' 结尾的指针修正为 's'。
    cur.execute(
        "UPDATE pointer SET target_synset_id = ("
        "  substr(target_synset_id, 1, length(target_synset_id)-1) || 's'"
        ") WHERE version = ?"
        "  AND substr(target_synset_id, -1) = 'a'"
        "  AND target_synset_id NOT IN (SELECT synset_id FROM synset)"
        "  AND (substr(target_synset_id, 1, length(target_synset_id)-1) || 's')"
        "      IN (SELECT synset_id FROM synset)",
        (version,),
    )
    corrected = cur.rowcount
    cur.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    msg = f"  pointer: {pointer_count} 行"
    if corrected > 0:
        msg += f" (adj satellite t_pos 校正: {corrected} 条)"
    print(msg)

    return synset_count, pointer_count, synset_frames


def import_lexical_entries(
    conn: sqlite3.Connection, dict_dir: Path, version: str
) -> Tuple[int, Dict[Tuple[str, str], Tuple[int, List[str]]]]:
    """导入 index.* 文件 -> lexical_entry 表。
    返回 (entry_count, {(lemma,pos): (entry_id, [offsets])})"""
    all_rows: List[Tuple] = []

    for pos in POS_FILES:
        index_path = dict_dir / f"index.{POS_TO_FILE[pos]}"
        if not index_path.exists():
            print(f"  [警告] 文件不存在: {index_path}")
            continue
        for row in parse_index_file(index_path, pos):
            all_rows.append(
                (
                    row["lemma"],
                    row["pos"],
                    row["synset_count"],
                    row["tagged_sense_count"],
                    row["pointer_symbols"],
                    row["offsets"],
                )
            )

    cur = conn.cursor()
    insert_batch = []
    for lemma, pos, sc, tsc, ps, _ in all_rows:
        insert_batch.append((lemma, pos, version, sc, tsc, ps))
        if len(insert_batch) >= BATCH_SIZE:
            cur.executemany(
                "INSERT INTO lexical_entry(lemma,pos,version,synset_count,tagged_sense_count,pointer_symbols) "
                "VALUES(?,?,?,?,?,?)",
                insert_batch,
            )
            insert_batch.clear()
    if insert_batch:
        cur.executemany(
            "INSERT INTO lexical_entry(lemma,pos,version,synset_count,tagged_sense_count,pointer_symbols) "
            "VALUES(?,?,?,?,?,?)",
            insert_batch,
        )
    conn.commit()

    # 构建 (lemma,pos) -> (entry_id, [offsets]) 映射
    lemma_offset_map: Dict[Tuple[str, str], Tuple[int, List[str]]] = {}
    for lemma, pos, sc, tsc, ps, offsets in all_rows:
        entry = cur.execute(
            "SELECT entry_id FROM lexical_entry WHERE lemma=? AND pos=? AND version=?",
            (lemma, pos, version),
        ).fetchone()
        if entry:
            key = (lemma, pos)
            if key not in lemma_offset_map:
                lemma_offset_map[key] = (entry[0], offsets)

    print(f"  lexical_entry: {len(lemma_offset_map)} 行")
    return len(lemma_offset_map), lemma_offset_map


def import_senses(
    conn: sqlite3.Connection,
    dict_dir: Path,
    version: str,
    lemma_offset_map: Dict[Tuple[str, str], Tuple[int, List[str]]],
) -> Tuple[int, Dict[str, int]]:
    """导入 index.sense -> sense 表。返回 (sense_count, {sense_key: sense_id})"""
    cur = conn.cursor()

    # 构建 (lemma, pos) -> entry_id 快速查找
    entry_lookup: Dict[Tuple[str, str], int] = {}
    for (lemma, pos), (entry_id, _) in lemma_offset_map.items():
        entry_lookup[(lemma, pos)] = entry_id

    sense_path = dict_dir / "index.sense"
    if not sense_path.exists():
        print("  [警告] index.sense 不存在，跳过 sense 导入")
        return 0, {}

    batch = []
    sense_count = 0
    skipped: List[Tuple[str, str, str]] = []  # (sense_key, reason, detail)

    for row in parse_sense_index(sense_path):
        sense_key = row["sense_key"]
        offset = row["offset"]
        pos = row["pos"]
        synset_id = f"{offset}{pos}"

        sk_lemma = sense_key.split("%")[0].lower()
        entry_pos = row["entry_pos"]

        entry_id = entry_lookup.get((sk_lemma, entry_pos))
        if entry_id is None:
            if len(skipped) < 20:
                skipped.append(
                    (sense_key, "entry未匹配", f"lemma='{sk_lemma}' pos='{entry_pos}'")
                )
            elif len(skipped) == 20:
                skipped.append(("...", "...", "..."))
            continue

        lex_id = 0
        m = re.search(r"%(\d+):(\d+):(\d+)", sense_key)
        if m:
            lex_id = int(m.group(3))

        batch.append(
            (
                synset_id,
                entry_id,
                sense_key,
                row["sense_number"],
                row["tag_cnt"],
                lex_id,
                version,
            )
        )

        if len(batch) >= BATCH_SIZE:
            cur.executemany(
                "INSERT INTO sense(synset_id,entry_id,sense_key,sense_number,tag_cnt,lex_id,version) "
                "VALUES(?,?,?,?,?,?,?)",
                batch,
            )
            sense_count += len(batch)
            batch.clear()

    if batch:
        cur.executemany(
            "INSERT INTO sense(synset_id,entry_id,sense_key,sense_number,tag_cnt,lex_id,version) "
            "VALUES(?,?,?,?,?,?,?)",
            batch,
        )
        sense_count += len(batch)

    conn.commit()

    # 打印跳过的详情
    total_skipped = (
        sum(1 for _ in open(sense_path, encoding="utf-8") if _.strip()) - sense_count
    )
    if skipped:
        print(
            f"  [详细] sense 匹配失败 (共 {total_skipped} 条，以下为前 {min(len(skipped), 20)} 例):"
        )
        for sk, reason, detail in skipped:
            print(f"    sense_key={sk} | {reason} | {detail}")
    elif total_skipped > 0:
        print(f"  [注意] sense 跳过 {total_skipped} 条（无匹配 entry）")

    # 构建 sense_key -> sense_id 映射
    sense_key_to_id: Dict[str, int] = {}
    rows = cur.execute(
        "SELECT sense_id, sense_key FROM sense WHERE version=?", (version,)
    ).fetchall()
    for sid, sk in rows:
        sense_key_to_id[sk] = sid

    print(
        f"  sense: {sense_count} 行"
        + (f" (跳过 {total_skipped} 条)" if total_skipped > 0 else "")
    )
    return sense_count, sense_key_to_id


def import_auxiliary_tables(
    conn: sqlite3.Connection,
    dict_dir: Path,
    version: str,
    synset_frames: Dict[str, List[int]],
    sense_key_to_id: Dict[str, int],
) -> Tuple[Dict[str, int], List[str], List[str]]:
    """导入辅助表: syntactic_frame, example_sentence, sense_frame, sense_example,
    morph_exception, sense_frequency
    返回 (counts, skipped_sentidx_keys, skipped_cntlist_keys)"""
    cur = conn.cursor()
    counts: Dict[str, int] = {}
    skipped_sentidx: List[str] = []
    skipped_cntlist: List[str] = []

    # -- syntactic_frame --
    frames_path = dict_dir / "verb.Framestext"
    frame_count = 0
    if frames_path.exists():
        batch = []
        for fn, ft in parse_frames(frames_path):
            batch.append((fn, ft))
            frame_count += 1
            if len(batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT OR IGNORE INTO syntactic_frame(frame_number,frame_text) VALUES(?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            cur.executemany(
                "INSERT OR IGNORE INTO syntactic_frame(frame_number,frame_text) VALUES(?,?)",
                batch,
            )
    conn.commit()
    counts["syntactic_frame"] = frame_count
    print(f"  syntactic_frame: {frame_count} 行")

    # -- example_sentence --
    sents_path = dict_dir / "sents.vrb"
    sent_count = 0
    if sents_path.exists():
        batch = []
        for sn, st in parse_sents(sents_path):
            batch.append((sn, st))
            sent_count += 1
            if len(batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT OR IGNORE INTO example_sentence(sentence_number,sentence_text) VALUES(?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            cur.executemany(
                "INSERT OR IGNORE INTO example_sentence(sentence_number,sentence_text) VALUES(?,?)",
                batch,
            )
    conn.commit()
    counts["example_sentence"] = sent_count
    print(f"  example_sentence: {sent_count} 行")

    # -- sense_frame --
    sf_count = 0
    sf_skipped = 0
    sf_seen: set = set()  # dedup: (sense_id, frame_number)
    batch = []
    for synset_id, frame_nums in synset_frames.items():
        sense_rows = cur.execute(
            "SELECT sense_id FROM sense WHERE synset_id=? AND version=?",
            (synset_id, version),
        ).fetchall()
        if not sense_rows:
            sf_skipped += len(frame_nums)
            continue
        for (sense_id,) in sense_rows:
            # 去重 frame 编号（单个 synset 可能有重复 frame）
            for fn in sorted(set(frame_nums)):
                key = (sense_id, fn)
                if key in sf_seen:
                    continue
                sf_seen.add(key)
                batch.append((sense_id, fn, version))
                sf_count += 1
                if len(batch) >= BATCH_SIZE:
                    cur.executemany(
                        "INSERT OR IGNORE INTO sense_frame(sense_id,frame_number,version) VALUES(?,?,?)",
                        batch,
                    )
                    batch.clear()
    if batch:
        cur.executemany(
            "INSERT OR IGNORE INTO sense_frame(sense_id,frame_number,version) VALUES(?,?,?)",
            batch,
        )
    conn.commit()
    counts["sense_frame"] = sf_count
    msg = f"  sense_frame: {sf_count} 行"
    if sf_skipped:
        msg += f" (跳过 {sf_skipped} 条无匹配 sense)"
    print(msg)

    # -- sense_example --
    sentidx_path = dict_dir / "sentidx.vrb"
    se_count = 0
    se_skipped = 0
    se_seen: set = set()  # dedup: sentidx.vrb 中 sense_key 可能重复出现
    if sentidx_path.exists():
        batch = []
        for sense_key, sent_nums in parse_sentidx(sentidx_path):
            sense_id = sense_key_to_id.get(sense_key)
            if sense_id is None:
                se_skipped += len(sent_nums)
                skipped_sentidx.append(sense_key)
                continue
            for sn in sent_nums:
                key = (sense_id, sn)
                if key in se_seen:
                    continue
                se_seen.add(key)
                batch.append((sense_id, sn, version))
                se_count += 1
                if len(batch) >= BATCH_SIZE:
                    cur.executemany(
                        "INSERT OR IGNORE INTO sense_example(sense_id,sentence_number,version) VALUES(?,?,?)",
                        batch,
                    )
                    batch.clear()
        if batch:
            cur.executemany(
                "INSERT OR IGNORE INTO sense_example(sense_id,sentence_number,version) VALUES(?,?,?)",
                batch,
            )
    conn.commit()
    counts["sense_example"] = se_count
    msg = f"  sense_example: {se_count} 行"
    if se_skipped:
        msg += f" (跳过 {se_skipped} 条无匹配 sense)"
    print(msg)

    # -- morph_exception --
    exc_count = 0
    batch = []
    for pos in POS_FILES:
        exc_path = dict_dir / f"{POS_TO_FILE[pos]}.exc"
        if exc_path.exists():
            for row in parse_exc(exc_path, pos):
                batch.append(
                    (row["pos"], row["surface_form"], row["base_form"], version)
                )
                exc_count += 1
                if len(batch) >= BATCH_SIZE:
                    cur.executemany(
                        "INSERT INTO morph_exception(pos,surface_form,base_form,version) VALUES(?,?,?,?)",
                        batch,
                    )
                    batch.clear()
    cousin_path = dict_dir / "cousin.exc"
    if cousin_path.exists():
        for row in parse_exc(cousin_path, "n"):
            batch.append((row["pos"], row["surface_form"], row["base_form"], version))
            exc_count += 1
    if batch:
        cur.executemany(
            "INSERT INTO morph_exception(pos,surface_form,base_form,version) VALUES(?,?,?,?)",
            batch,
        )
    conn.commit()
    counts["morph_exception"] = exc_count
    print(f"  morph_exception: {exc_count} 行")

    # -- sense_frequency --
    cntlist_path = dict_dir / "cntlist"
    freq_count = 0
    freq_skipped = 0
    if cntlist_path.exists():
        batch = []
        for row in parse_cntlist(cntlist_path):
            sense_id = sense_key_to_id.get(row["sense_key"])
            if sense_id is None:
                freq_skipped += 1
                skipped_cntlist.append(row["sense_key"])
                continue
            batch.append((sense_id, row["count"], row["rank"], version))
            freq_count += 1
            if len(batch) >= BATCH_SIZE:
                cur.executemany(
                    "INSERT INTO sense_frequency(sense_id,count,rank,version) VALUES(?,?,?,?)",
                    batch,
                )
                batch.clear()
        if batch:
            cur.executemany(
                "INSERT INTO sense_frequency(sense_id,count,rank,version) VALUES(?,?,?,?)",
                batch,
            )
    conn.commit()
    counts["sense_frequency"] = freq_count
    msg = f"  sense_frequency: {freq_count} 行"
    if freq_skipped:
        msg += f" (跳过 {freq_skipped} 条无匹配 sense)"
    print(msg)

    return counts, skipped_sentidx, skipped_cntlist


def resolve_pointer_senses(
    conn: sqlite3.Connection, version: str, log_dir: Path
) -> Dict[str, Dict[str, int]]:
    """补全 pointer 表中的 source_sense_id 和 target_sense_id（词级指针）。
    返回未解析词级引用的统计: {"source": {sym: count}, "target": {sym: count}}"""
    cur = conn.cursor()

    cur.execute(
        "SELECT sense_id, synset_id, lex_id FROM sense WHERE version=?", (version,)
    )
    sense_index: Dict[Tuple[str, int], int] = {}
    for sid, synset_id, lex_id in cur.fetchall():
        key = (synset_id, lex_id)
        if key not in sense_index:
            sense_index[key] = sid

    cur.execute(
        "SELECT pointer_id, source_synset_id, target_synset_id, "
        "source_w_num, target_w_num, symbol "
        "FROM pointer WHERE version=? AND (source_w_num > 0 OR target_w_num > 0)",
        (version,),
    )

    updates = []
    unresolved = 0
    # 统计未解析的词级指针（按来源/目标和符号分组）
    unresolved_stats: Dict[str, Dict[str, int]] = {"source": {}, "target": {}}
    # 收集无法解析的详细条目，用于写入独立日志
    unresolved_entries: List[Tuple[str, str, str, int, int]] = []
    # (direction, symbol, synset_id, w_num, lex_id)
    for pid, src_syn, tgt_syn, src_w, tgt_w, sym in cur.fetchall():
        src_sense = None
        tgt_sense = None
        if src_w > 0:
            lex_id = src_w - 1
            src_sense = sense_index.get((src_syn, lex_id))
            if src_sense is None:
                unresolved += 1
                unresolved_stats["source"][sym] = (
                    unresolved_stats["source"].get(sym, 0) + 1
                )
                unresolved_entries.append(("source", sym, src_syn, src_w, lex_id))
        if tgt_w > 0:
            lex_id = tgt_w - 1
            tgt_sense = sense_index.get((tgt_syn, lex_id))
            if tgt_sense is None:
                unresolved += 1
                unresolved_stats["target"][sym] = (
                    unresolved_stats["target"].get(sym, 0) + 1
                )
                unresolved_entries.append(("target", sym, tgt_syn, tgt_w, lex_id))

        if src_sense is not None or tgt_sense is not None:
            updates.append((src_sense, tgt_sense, pid))

    if updates:
        cur.executemany(
            "UPDATE pointer SET source_sense_id=?, target_sense_id=? WHERE pointer_id=?",
            updates,
        )
        conn.commit()

    print(
        f"  pointer sense 引用补全: {len(updates)} 条"
        + (f" (无法解析词级引用: {unresolved} 条)" if unresolved else "")
    )
    if unresolved > 0:
        # 按符号分组显示未解析的统计
        all_symbols = set(
            list(unresolved_stats["source"].keys())
            + list(unresolved_stats["target"].keys())
        )
        detail_parts = []
        for sym in sorted(
            all_symbols,
            key=lambda s: unresolved_stats["source"].get(s, 0)
            + unresolved_stats["target"].get(s, 0),
            reverse=True,
        ):
            s_cnt = unresolved_stats["source"].get(sym, 0)
            t_cnt = unresolved_stats["target"].get(sym, 0)
            detail_parts.append(f"{sym}(src={s_cnt},tgt={t_cnt})")
        print(f"    未解析分布: {', '.join(detail_parts[:10])}")

    # 写入无法解析的词级指针详情到独立文件
    if unresolved_entries:
        ptr_log_path = log_dir / f"import_wn{version}_unresolved_pointers.log"
        ptr_lines: List[str] = []
        ptr_lines.append(f"===== WordNet {version} 词级指针无法解析详情 =====")
        ptr_lines.append(f"总计: {len(unresolved_entries)} 条")
        ptr_lines.append("格式: direction | symbol | synset_id | w_num | lex_id")
        ptr_lines.append(
            "原因: (synset_id, lex_id) 组合在 index.sense 中无对应 sense 记录"
        )
        ptr_lines.append("")
        for direction, sym, syn_id, w_num, lex_id in unresolved_entries:
            ptr_lines.append(f"{direction}\t{sym}\t{syn_id}\t{w_num}\t{lex_id}")
        ptr_log_path.write_text("\n".join(ptr_lines), encoding="utf-8")
        print(f"    详细条目已写入: {ptr_log_path} ({len(unresolved_entries)} 条)")

    return unresolved_stats


# ── 数据问题日志 ──


def format_data_issues(
    version: str,
    unresolved_stats: Dict[str, Dict[str, int]],
    skipped_sentidx: List[str],
    skipped_cntlist: List[str],
) -> str:
    """格式化已知数据问题（非代码 bug）的详细日志。"""
    lines: List[str] = []
    lines.append("")
    lines.append("===== 已知数据问题（非代码 bug）=====")
    lines.append("以下问题源自 WordNet 3.1 官方数据集的内部不一致。")
    lines.append("")

    # 1. 词级指针无法解析到 sense
    total_source = sum(unresolved_stats["source"].values())
    total_target = sum(unresolved_stats["target"].values())
    unique = total_source + total_target  # 每个 source/target 方向独立计数
    lines.append("--- 1. 词级指针无法解析到 sense ---")
    lines.append(f"data.* 文件中的词级指针 (w_num>0) 需要根据 (synset_id, lex_id) 匹配")
    lines.append(
        f"sense 表中的记录，但 {unique} 条引用无法在 index.sense 中找到对应条目"
    )
    lines.append(f"  - source 方向 (source_w_num>0 无匹配 sense): {total_source} 条")
    lines.append(f"  - target 方向 (target_w_num>0 无匹配 sense): {total_target} 条")
    lines.append("")
    lines.append("  按指针符号分布:")
    all_symbols = set(
        list(unresolved_stats["source"].keys())
        + list(unresolved_stats["target"].keys())
    )
    for sym in sorted(
        all_symbols,
        key=lambda s: unresolved_stats["source"].get(s, 0)
        + unresolved_stats["target"].get(s, 0),
        reverse=True,
    ):
        s_cnt = unresolved_stats["source"].get(sym, 0)
        t_cnt = unresolved_stats["target"].get(sym, 0)
        lines.append(f"    {sym}: source={s_cnt}, target={t_cnt}")
    lines.append("")
    lines.append(f"  详细条目见: db/import_wn{version}_unresolved_pointers.log")

    # 2. sentidx.vrb 无匹配 sense
    lines.append("")
    lines.append("--- 2. sentidx.vrb 中 sense_key 无法匹配 sense 表 ---")
    lines.append(f"共 {len(skipped_sentidx)} 条 sense_key 在 index.sense 中不存在：")
    for sk in skipped_sentidx:
        lines.append(f"    {sk}")

    # 3. cntlist 无匹配 sense
    lines.append("")
    lines.append("--- 3. cntlist 中 sense_key 无法匹配 sense 表 ---")
    lines.append(f"共 {len(skipped_cntlist)} 条 sense_key 在 index.sense 中不存在：")
    for sk in skipped_cntlist:
        lines.append(f"    {sk}")

    lines.append("")
    lines.append("===== 数据问题报告结束 =====")
    return "\n".join(lines)


# ── 校验模块 ──


def count_file_lines(filepath: Path) -> int:
    """统计文件的非注释非空行数（与解析器相同的过滤逻辑）。"""
    count = 0
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("  ") or line.startswith("This"):
                continue
            parts = line.split()
            if not parts:
                continue
            # 使用与解析器相同的格式验证
            if "data." in filepath.name:
                # data.* 文件: 第一个字段必须是 8 位数字
                if not (parts[0].isdigit() and len(parts[0]) == 8):
                    continue
                if " | " not in line:
                    continue
            elif "index." in filepath.name and filepath.name != "index.sense":
                # index.* 文件: 第二个字段必须是有效词性
                if len(parts) < 3:
                    continue
                if parts[1] not in ("n", "v", "a", "r"):
                    continue
                if not parts[2].isdigit():
                    continue
            elif filepath.name == "index.sense":
                # index.sense: 至少 4 个字段
                if len(parts) < 4:
                    continue
            # else: *.exc 等文件无特殊过滤
            count += 1
    return count


def validate(
    conn: sqlite3.Connection,
    dict_dir: Path,
    version: str,
    import_counts: Dict[str, int],
) -> Tuple[str, str]:
    """执行校验，返回 (log_text, error_summary)。

    import_counts 包含导入阶段实际统计的各类记录数：
    - synset, pointer, entry, sense
    - syntactic_frame, example_sentence, sense_frame, sense_example,
      morph_exception, sense_frequency
    """
    cur = conn.cursor()
    lines: List[str] = []
    errors: List[str] = []

    def log(msg: str):
        lines.append(msg)

    def err(msg: str):
        lines.append(f"  [FAIL] {msg}")
        errors.append(msg)

    def ok(msg: str):
        lines.append(f"  [PASS] {msg}")

    log(f"===== WordNet {version} 导入校验报告 =====")
    log(f"校验时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"源文件: wn{version}.dict.tar.gz")
    log("")

    # ── Layer 1: 行数校验 ──
    log("--- 1. 行数校验 (文件 vs 数据库) ---")

    line_checks = [
        ("data.noun", "SELECT COUNT(*) FROM synset WHERE pos='n' AND version=?"),
        ("data.verb", "SELECT COUNT(*) FROM synset WHERE pos='v' AND version=?"),
        (
            "data.adj",
            "SELECT COUNT(*) FROM synset WHERE pos IN ('a','s') AND version=?",
        ),
        ("data.adv", "SELECT COUNT(*) FROM synset WHERE pos='r' AND version=?"),
        (
            "index.noun",
            "SELECT COUNT(*) FROM lexical_entry WHERE pos='n' AND version=?",
        ),
        (
            "index.verb",
            "SELECT COUNT(*) FROM lexical_entry WHERE pos='v' AND version=?",
        ),
        ("index.adj", "SELECT COUNT(*) FROM lexical_entry WHERE pos='a' AND version=?"),
        ("index.adv", "SELECT COUNT(*) FROM lexical_entry WHERE pos='r' AND version=?"),
        ("index.sense", "SELECT COUNT(*) FROM sense WHERE version=?"),
    ]

    for fname, sql in line_checks:
        fpath = dict_dir / fname
        if not fpath.exists():
            log(f"  {fname}: 文件不存在，跳过")
            continue
        file_lines = count_file_lines(fpath)
        db_count = cur.execute(sql, (version,)).fetchone()[0]
        status = "PASS" if file_lines == db_count else "FAIL"
        log(f"  {fname}: 文件 {file_lines} 行 -> 数据库 {db_count} 行 [{status}]")
        if status == "FAIL":
            err(
                f"行数不匹配: {fname} (文件={file_lines}, 数据库={db_count}, 差异={file_lines - db_count})"
            )

    # *.exc 合计
    exc_total = 0
    for pos in POS_FILES:
        exc_path = dict_dir / f"{POS_TO_FILE[pos]}.exc"
        if exc_path.exists():
            exc_total += count_file_lines(exc_path)
    cousin_path = dict_dir / "cousin.exc"
    if cousin_path.exists():
        exc_total += count_file_lines(cousin_path)
    db_exc = cur.execute(
        "SELECT COUNT(*) FROM morph_exception WHERE version=?", (version,)
    ).fetchone()[0]
    status = "PASS" if exc_total == db_exc else "FAIL"
    log(f"  *.exc (合计): 文件 {exc_total} 行 -> 数据库 {db_exc} 行 [{status}]")
    if status == "FAIL":
        err(f"exc 行数不匹配 (文件={exc_total}, 数据库={db_exc})")

    log("")

    # ── Layer 2: 导入计数校验（解析时统计 vs 数据库实际） ──
    log("--- 2. 导入计数校验 (解析统计 vs 数据库) ---")

    check_map = [
        ("synset", "SELECT COUNT(*) FROM synset WHERE version=?"),
        ("pointer", "SELECT COUNT(*) FROM pointer WHERE version=?"),
        ("entry", "SELECT COUNT(*) FROM lexical_entry WHERE version=?"),
        ("sense", "SELECT COUNT(*) FROM sense WHERE version=?"),
        ("syntactic_frame", "SELECT COUNT(*) FROM syntactic_frame"),
        ("example_sentence", "SELECT COUNT(*) FROM example_sentence"),
        ("sense_frame", "SELECT COUNT(*) FROM sense_frame WHERE version=?"),
        ("sense_example", "SELECT COUNT(*) FROM sense_example WHERE version=?"),
        ("morph_exception", "SELECT COUNT(*) FROM morph_exception WHERE version=?"),
        ("sense_frequency", "SELECT COUNT(*) FROM sense_frequency WHERE version=?"),
    ]

    for key, sql in check_map:
        expected = import_counts.get(key, 0)
        if "?" in sql:
            actual = cur.execute(sql, (version,)).fetchone()[0]
        else:
            actual = cur.execute(sql).fetchone()[0]
        status = "PASS" if expected == actual else "FAIL"
        log(f"  {key}: 解析 {expected} -> 数据库 {actual} [{status}]")
        if status == "FAIL":
            err(
                f"导入计数不匹配: {key} (解析={expected}, 数据库={actual}, 差异={expected - actual})"
            )

    log("")

    # ── Layer 3: 引用完整性 ──
    log("--- 3. 引用完整性 ---")

    fk_checks = [
        (
            "pointer.source_synset -> synset",
            "SELECT COUNT(*) FROM pointer WHERE version=? AND "
            "source_synset_id NOT IN (SELECT synset_id FROM synset)",
        ),
        (
            "pointer.target_synset -> synset",
            "SELECT COUNT(*) FROM pointer WHERE version=? AND "
            "target_synset_id NOT IN (SELECT synset_id FROM synset)",
        ),
        (
            "sense.synset_id -> synset",
            "SELECT COUNT(*) FROM sense WHERE version=? AND "
            "synset_id NOT IN (SELECT synset_id FROM synset)",
        ),
        (
            "sense.entry_id -> lexical_entry",
            "SELECT COUNT(*) FROM sense WHERE version=? AND "
            "entry_id NOT IN (SELECT entry_id FROM lexical_entry)",
        ),
    ]

    for label, sql in fk_checks:
        orphan = cur.execute(sql, (version,)).fetchone()[0]
        if orphan == 0:
            ok(f"{label}: 0 孤立引用")
        else:
            err(f"{label}: {orphan} 条孤立引用")

    log("")

    # ── Layer 4: 全局统计 ──
    log("--- 4. 全局统计 ---")

    total_synset = cur.execute(
        "SELECT COUNT(*) FROM synset WHERE version=?", (version,)
    ).fetchone()[0]
    total_pointer = cur.execute(
        "SELECT COUNT(*) FROM pointer WHERE version=?", (version,)
    ).fetchone()[0]
    total_sense = cur.execute(
        "SELECT COUNT(*) FROM sense WHERE version=?", (version,)
    ).fetchone()[0]
    total_entry = cur.execute(
        "SELECT COUNT(*) FROM lexical_entry WHERE version=?", (version,)
    ).fetchone()[0]
    unique_lemma = cur.execute(
        "SELECT COUNT(DISTINCT lemma) FROM lexical_entry WHERE version=?", (version,)
    ).fetchone()[0]

    log(f"  Synset 总计:        {total_synset}")
    log(f"  Pointer 总计:       {total_pointer}")
    log(f"  Sense 总计:         {total_sense}")
    log(f"  LexicalEntry 总计:  {total_entry}")
    log(f"  唯一词形:            {unique_lemma}")
    log(f"  syntactic_frame:    {import_counts.get('syntactic_frame', 0)}")
    log(f"  example_sentence:   {import_counts.get('example_sentence', 0)}")
    log(f"  sense_frame:        {import_counts.get('sense_frame', 0)}")
    log(f"  sense_example:      {import_counts.get('sense_example', 0)}")
    log(f"  morph_exception:    {import_counts.get('morph_exception', 0)}")
    log(f"  sense_frequency:    {import_counts.get('sense_frequency', 0)}")

    log("")

    if errors:
        log(f"===== 结果: {len(errors)} 项 FAIL =====")
        error_summary = "; ".join(errors)
    else:
        log("===== 结果: ALL PASS =====")
        error_summary = ""

    return "\n".join(lines), error_summary


# ── 主流程 ──


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  WordNet 字典 -> SQLite 导入工具")
    print("=" * 60)

    archives = find_archives()
    print(f"\n[扫描] 找到 {len(archives)} 个压缩包")
    for a in archives:
        print(f"  - {a.name}")

    conn = get_conn()

    existing_versions: set = set()
    cur = conn.cursor()
    for row in cur.execute("SELECT version FROM import_meta"):
        existing_versions.add(row[0])

    for archive_path in archives:
        version = parse_version(archive_path)

        if version in existing_versions:
            print(f"\n[跳过] 版本 {version} 已导入 (import_meta 记录存在)")
            continue

        # 清理旧数据（如果有残留）
        cur.execute("SELECT COUNT(*) FROM synset WHERE version=?", (version,))
        if cur.fetchone()[0] > 0:
            _delete_version_data(conn, version)

        print(f"\n{'=' * 60}")
        print(f"  开始导入版本 {version}")
        print(f"{'=' * 60}")

        dict_dir = extract_archive(archive_path)

        # 导入（按外键依赖顺序）
        print("\n[导入] synset + pointer ...")
        s_cnt, p_cnt, synset_frames = import_synsets_and_pointers(
            conn, dict_dir, version
        )

        print("\n[导入] lexical_entry ...")
        e_cnt, lemma_offset_map = import_lexical_entries(conn, dict_dir, version)

        print("\n[导入] sense ...")
        se_cnt, sense_key_to_id = import_senses(
            conn, dict_dir, version, lemma_offset_map
        )

        print("\n[导入] 辅助表 ...")
        aux_counts, skipped_sentidx, skipped_cntlist = import_auxiliary_tables(
            conn, dict_dir, version, synset_frames, sense_key_to_id
        )

        print("\n[处理] pointer sense 引用补全 ...")
        unresolved_ptr_stats = resolve_pointer_senses(conn, version, LOG_DIR)

        # 汇总所有计数
        import_counts = {
            "synset": s_cnt,
            "pointer": p_cnt,
            "entry": e_cnt,
            "sense": se_cnt,
            **aux_counts,
        }

        # 校验
        print("\n[校验] 数据完整性 ...")
        log_text, error_summary = validate(conn, dict_dir, version, import_counts)

        # 追加已知数据问题详情
        data_issues_text = format_data_issues(
            version, unresolved_ptr_stats, skipped_sentidx, skipped_cntlist
        )
        log_text += "\n" + data_issues_text

        log_path = LOG_DIR / f"import_wn{version}.log"
        log_path.write_text(log_text, encoding="utf-8")
        print(f"  校验日志: {log_path}")

        conn.execute(
            "INSERT INTO import_meta("
            "version, source_file, synset_count, pointer_count,"
            "sense_count, entry_count, log_path, error_summary, created_at"
            ") VALUES(?,?,?,?,?,?,?,?,?)",
            (
                version,
                archive_path.name,
                s_cnt,
                p_cnt,
                se_cnt,
                e_cnt,
                str(log_path),
                error_summary if error_summary else None,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()

        if error_summary:
            print(f"\n  [WARN] 校验发现问题: {error_summary}")
            print(f"  详情见: {log_path}")
        else:
            print(f"\n  [OK] 版本 {version} 导入完成，校验全部通过！")

    conn.close()
    print("\n完成！")


if __name__ == "__main__":
    main()
