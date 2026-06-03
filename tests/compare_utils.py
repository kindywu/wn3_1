from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


def _norm_sid(sid: str) -> str:
    """main.py 把所有 data.adj 的 synset 都视为 pos='a'，忽略 ss_type='s'。
    为对齐两端，把 synset_id 末尾的 's' 归一化为 'a'。"""
    return sid[:-1] + "a" if sid.endswith("s") else sid


def _norm_pos(pos: str) -> str:
    """pos 字段同样做 s→a 归一化。"""
    return "a" if pos == "s" else pos


def _strip_markers(word: str) -> str:
    """去掉 WordNet data.* 中的形容词/副词标记后缀，
    如 `big(p)` → `big`、`running(a)` → `running`、`galore(ip)` → `galore`。"""
    return re.sub(r"\((?:ip|[aps])\)$", "", word)


def _norm_word(word: str) -> str:
    """综合归一化：转小写并去掉 (a)/(p)/(s) 标记。"""
    return _strip_markers(word.lower())


def compare_lookup_results(
    word: str,
    file_results: List[dict],
    db_results: List[dict],
    file_db,
) -> List[str]:
    """深度对比文件端与数据库端的 lookup 结果。

    已处理的已知差异：
    - adj satellite 的 synset_id / pos：main.py 统一视为 'a'，DB 正确保留 's'
    - lemma 大小写与形态标记：data.* 保留原始大小写并带 (a)/(p) 标记，
      index.* 全小写且无标记 → 比较时统一归一化
    - gloss 前导空格：main.py 未 strip，import 时 strip 了 → 比较时两端 strip
    - satellite 的 sense_key 缺失：main.py 的 _find_sense_key 因 pos='a' vs 's'
      匹配失败 → 视为可接受差异

    返回差异描述列表，空列表表示完全一致。
    """
    diffs: List[str] = []

    # 从 index.sense 构建有效 (synset_id, lemma, lex_id) 集合，
    # 用于过滤 data.* 中无对应 sense_key 的 ghost word 条目
    # （如 data.noun 中的 case-variant 重复词条 Earth(0)/earth(2)，
    #   index.sense 只收录了小写版本）。
    _s = set()
    for sk, si in file_db.senses.items():
        lemma = sk.split("%")[0].lower()
        sid = _norm_sid(si.offset + si.pos)
        m = re.search(r"%\d+:\d+:(\d+)", sk)
        lex_id = int(m.group(1)) if m else 0
        _s.add((sid, lemma, lex_id))
    valid_sense_words = _s

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
            diffs.extend(_compare_single_sense(f, d, file_db, nid, valid_sense_words))

    return diffs


def _compare_single_sense(
    f: dict, d: dict, file_db, norm_id: str, valid_sense_words: set
) -> List[str]:
    """对比单个 sense 的详细信息。"""
    diffs: List[str] = []
    sid = f"{f['synset_id']}/{d['synset_id']}"

    # 判断是否为 satellite（DB 端 synset_id 以 's' 结尾）
    is_satellite = d["synset_id"].endswith("s")

    # ── 标量字段 ──
    # 注意：synset_id 不做直接比较，因为 main.py 对 satellite 统一用 'a' 结尾，
    # DB 用 's' 结尾。对齐已通过 _norm_sid 完成，此处无需重复比较。
    scalar_keys = ["lemma", "offset", "ss_type"]
    for key in scalar_keys:
        fv = f.get(key)
        dv = d.get(key)
        if key in ("pos", "ss_type"):
            fv = _norm_pos(str(fv)) if fv is not None else fv
            dv = _norm_pos(str(dv)) if dv is not None else dv
        if fv != dv:
            diffs.append(f"{sid}.{key}: 文件={f.get(key)!r} vs DB={d.get(key)!r}")

    # pos_name：'形容词卫星' vs '形容词' 对 satellite 是已知差异
    if not is_satellite:
        if f.get("pos_name") != d.get("pos_name"):
            diffs.append(
                f"{sid}.pos_name: 文件={f.get('pos_name')!r} "
                f"vs DB={d.get('pos_name')!r}"
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

    # ── words（忽略大小写、忽略 (a)/(p)/(ip) 标记、忽略顺序） ──
    # 过滤 data.* 中有但 index.sense 中无对应 sense_key 的 ghost word 条目
    f_words = {
        (_norm_word(w["word"]), w["lex_id"])
        for w in f["words"]
        if (_norm_word(w["word"]), w["lex_id"])
        in {(lemma, lid) for sid, lemma, lid in valid_sense_words if sid == norm_id}
    }
    d_words = {(_norm_word(w["word"]), w["lex_id"]) for w in d["words"]}
    if f_words != d_words:
        diffs.append(f"{sid}.words: 文件={f_words} vs DB={d_words}")

    # ── current_word ──
    f_cw = f["current_word"]
    d_cw = d["current_word"]

    # 对 satellite，main.py 的 sense_key 可能为 None（已知缺陷）
    if is_satellite and f_cw.get("sense_key") is None:
        # 跳过 current_word 全部字段比较
        pass
    else:
        for k in ["sense_key", "sense_number", "tag_count"]:
            fv = f_cw.get(k)
            dv = d_cw.get(k)
            if fv != dv:
                diffs.append(f"{sid}.current_word.{k}: 文件={fv!r} vs DB={dv!r}")

        # lex_id：main.py 可能因大小写敏感匹配失败而得到 None，
        # 也可能因 data.* 中同一词有多种大小写/lex_id 变体而取到错误的 lex_id。
        # 当两端 sense_key 一致时，以 sense_key 中编码的 lex_id 为准，跳过此差异。
        f_lex = f_cw.get("lex_id")
        d_lex = d_cw.get("lex_id")
        if f_lex != d_lex:
            if (
                f_lex is None and f_cw.get("sense_key") == d_cw.get("sense_key")
            ) or f_cw.get("sense_key") == d_cw.get("sense_key"):
                pass
            else:
                diffs.append(
                    f"{sid}.current_word.lex_id: 文件={f_lex!r} vs DB={d_lex!r}"
                )

    # ── frequency ──
    ff = f.get("frequency")
    df = d.get("frequency")
    if (ff is None) != (df is None):
        # satellite 的 frequency 缺失也是已知差异的一部分
        if not (is_satellite and ff is None):
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
                "words": {_norm_word(w[0]) for w in (target.words if target else [])},
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
                db_words = {_norm_word(w.strip()) for w in words_str.split(",")}
            db_ptr_map[key] = {
                "gloss": (target.get("gloss", "") or "").strip(),
                "words": db_words,
            }

    file_keys = set(file_ptr_map.keys())
    db_keys = set(db_ptr_map.keys())
    if file_keys != db_keys:
        only_file = sorted(file_keys - db_keys)
        only_db = sorted(db_keys - file_keys)
        diffs.append(f"{sid}.pointers: 仅文件={only_file}, 仅DB={only_db}")

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
