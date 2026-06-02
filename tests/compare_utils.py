from __future__ import annotations

from typing import Dict, List, Set, Tuple


def _norm_sid(sid: str) -> str:
    """main.py 把所有 data.adj 的 synset 都视为 pos='a'，忽略 ss_type='s'。
    为对齐两端，把 synset_id 末尾的 's' 归一化为 'a'。"""
    return sid[:-1] + "a" if sid.endswith("s") else sid


def _norm_pos(pos: str) -> str:
    """pos 字段同样做 s→a 归一化。"""
    return "a" if pos == "s" else pos


def compare_lookup_results(
    word: str,
    file_results: List[dict],
    db_results: List[dict],
    file_db,
) -> List[str]:
    """深度对比文件端与数据库端的 lookup 结果。

    已处理的已知差异：
    - adj satellite 的 synset_id / pos：main.py 统一视为 'a'，DB 正确保留 's'
    - lemma 大小写：index.* 全小写，data.* 保留原始大小写 → 忽略大小写比较
    - gloss 前导空格：main.py 未 strip，import 时 strip 了 → 比较时两端 strip
    - lex_id 为 None：main.py 大小写敏感匹配可能失败 → sense_key 一致即可接受

    返回差异描述列表，空列表表示完全一致。
    """
    diffs: List[str] = []

    # 用归一化后的 synset_id 对齐（处理 s/a 差异）
    file_norm: Dict[str, List[dict]] = {}
    for r in file_results:
        file_norm.setdefault(_norm_sid(r["synset_id"]), []).append(r)

    db_norm: Dict[str, List[dict]] = {}
    for r in db_results:
        db_norm.setdefault(_norm_sid(r["synset_id"]), []).append(r)

    all_ids = sorted(set(file_norm) | set(db_norm))

    for nid in all_ids:
        f_list = file_norm.get(nid, [])
        d_list = db_norm.get(nid, [])

        if not f_list:
            for d in d_list:
                diffs.append(f"{d['synset_id']}: 文件端缺失")
            continue
        if not d_list:
            for f in f_list:
                diffs.append(f"{f['synset_id']}: DB端缺失")
            continue

        if len(f_list) != len(d_list):
            diffs.append(
                f"{nid}: 文件端 {len(f_list)} 个 sense vs DB端 {len(d_list)} 个 sense"
            )
            continue

        for f, d in zip(f_list, d_list):
            diffs.extend(_compare_single_sense(f, d, file_db, nid))

    return diffs


def _compare_single_sense(
    f: dict, d: dict, file_db, norm_id: str
) -> List[str]:
    """对比单个 sense 的详细信息。"""
    diffs: List[str] = []
    sid = f"{f['synset_id']}/{d['synset_id']}"

    # ── 标量字段 ──
    scalar_keys = ["lemma", "synset_id", "offset", "ss_type", "pos_name"]
    for key in scalar_keys:
        fv = f.get(key)
        dv = d.get(key)
        # pos / ss_type 中的 's' 与 'a' 视为等价
        if key in ("pos", "ss_type"):
            fv = _norm_pos(str(fv)) if fv is not None else fv
            dv = _norm_pos(str(dv)) if dv is not None else dv
        if fv != dv:
            diffs.append(
                f"{sid}.{key}: 文件={f.get(key)!r} vs DB={d.get(key)!r}"
            )

    # lex_filenum：统一按字符串比较（已处理前导零）
    if str(f.get("lex_filenum")) != str(d.get("lex_filenum")):
        diffs.append(
            f"{sid}.lex_filenum: 文件={f.get('lex_filenum')!r} "
            f"vs DB={d.get('lex_filenum')!r}"
        )

    # ── gloss（strip 后比较） ──
    fg = (f.get("gloss") or "").strip()
    dg = (d.get("gloss") or "").strip()
    if fg != dg:
        diffs.append(f"{sid}.gloss: 文件={fg!r} vs DB={dg!r}")

    # ── words（忽略大小写、忽略顺序） ──
    f_words = {(w["word"].lower(), w["lex_id"]) for w in f["words"]}
    d_words = {(w["word"].lower(), w["lex_id"]) for w in d["words"]}
    if f_words != d_words:
        diffs.append(f"{sid}.words: 文件={f_words} vs DB={d_words}")

    # ── current_word ──
    for k in ["sense_key", "sense_number", "tag_count"]:
        fv = f["current_word"].get(k)
        dv = d["current_word"].get(k)
        if fv != dv:
            diffs.append(
                f"{sid}.current_word.{k}: 文件={fv!r} vs DB={dv!r}"
            )

    # lex_id：main.py 可能因大小写敏感匹配失败而得到 None
    f_lex = f["current_word"].get("lex_id")
    d_lex = d["current_word"].get("lex_id")
    if f_lex != d_lex:
        # 若文件端为 None 但 sense_key 一致，视为可接受的已知差异
        if f_lex is None and f["current_word"].get("sense_key") == d[
            "current_word"
        ].get("sense_key"):
            pass
        else:
            diffs.append(
                f"{sid}.current_word.lex_id: 文件={f_lex!r} vs DB={d_lex!r}"
            )

    # ── frequency ──
    ff = f.get("frequency")
    df = d.get("frequency")
    if (ff is None) != (df is None):
        diffs.append(f"{sid}.frequency: 文件={ff!r} vs DB={df!r}")
    elif ff is not None:
        if ff["count"] != df["count"] or ff["rank"] != df["rank"]:
            diffs.append(f"{sid}.frequency: 文件={ff!r} vs DB={df!r}")

    # ── pointers（核心元组 + target 详情） ──
    file_synset = file_db.synsets.get(f["synset_id"])
    file_ptr_map: Dict[Tuple, dict] = {}
    if file_synset:
        for p in file_synset.pointers:
            key = (
                p.symbol,
                _norm_sid(p.target_offset + p.pos),
                p.source_w_num,
                p.target_w_num,
            )
            target = file_db.synsets.get(p.target_offset + p.pos)
            file_ptr_map[key] = {
                "gloss": (target.gloss if target else "").strip(),
                "words": {
                    w[0].lower() for w in (target.words if target else [])
                },
            }

    db_ptr_map: Dict[Tuple, dict] = {}
    for desc, ptrs in d["pointers"].items():
        for p in ptrs:
            target = p["target"]
            key = (
                p["symbol"],
                _norm_sid(target["offset"] + target["pos"]),
                p.get("source_w_num", 0),
                p.get("target_w_num", 0),
            )
            words_str = target["words"]
            db_words = set()
            if words_str != "(未加载)":
                db_words = {w.strip().lower() for w in words_str.split(",")}
            db_ptr_map[key] = {
                "gloss": (target.get("gloss", "") or "").strip(),
                "words": db_words,
            }

    file_keys = set(file_ptr_map.keys())
    db_keys = set(db_ptr_map.keys())
    if file_keys != db_keys:
        only_file = sorted(file_keys - db_keys)
        only_db = sorted(db_keys - file_keys)
        diffs.append(
            f"{sid}.pointers: 仅文件={only_file}, 仅DB={only_db}"
        )

    for key in file_keys & db_keys:
        fm = file_ptr_map[key]
        dm = db_ptr_map[key]
        if fm["gloss"] != dm["gloss"]:
            diffs.append(
                f"{sid}.pointers{key}.gloss: "
                f"文件={fm['gloss']!r} vs DB={dm['gloss']!r}"
            )
        if fm["words"] != dm["words"]:
            diffs.append(
                f"{sid}.pointers{key}.target_words: "
                f"文件={fm['words']} vs DB={dm['words']}"
            )

    # ── frames（集合比较，消除可能的重复） ──
    f_frames = {(fr["frame_id"], fr["frame"]) for fr in f.get("frames", [])}
    d_frames = {(fr["frame_id"], fr["frame"]) for fr in d.get("frames", [])}
    if f_frames != d_frames:
        diffs.append(f"{sid}.frames: 文件={f_frames} vs DB={d_frames}")

    # ── examples（集合比较） ──
    f_ex = {(ex["id"], ex["text"]) for ex in f.get("examples", [])}
    d_ex = {(ex["id"], ex["text"]) for ex in d.get("examples", [])}
    if f_ex != d_ex:
        diffs.append(f"{sid}.examples: 文件={f_ex} vs DB={d_ex}")

    return diffs
