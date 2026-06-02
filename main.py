#!/usr/bin/env python3
"""
WordNet 3.1 全能查询工具
支持跨文件全引用追踪：index -> data -> sense -> cntlist -> frames -> sents -> exc
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

# ─────────────────────────── 配置 ───────────────────────────
DICT_DIR = Path(__file__).parent / "dict"

# ss_type 编码映射
SS_TYPE_MAP = {
    "n": "名词",
    "v": "动词",
    "a": "形容词",
    "r": "副词",
    "s": "形容词卫星",
}

SS_TYPE_CODE = {
    "n": 1,
    "v": 2,
    "a": 3,
    "r": 4,
    "s": 5,
}

# 指针符号 -> 名称与方向
POINTER_DESC = {
    "!":  "反义词 (Antonym)",
    "@":  "上位词 (Hypernym)",
    "@i": "实例上位词 (Instance Hypernym)",
    "~":  "下位词 (Hyponym)",
    "~i": "实例下位词 (Instance Hyponym)",
    "#m": "成员部分 (Member Meronym)",
    "#s": "物质部分 (Substance Meronym)",
    "#p": "部件部分 (Part Meronym)",
    "%m": "成员整体 (Member Holonym)",
    "%s": "物质整体 (Substance Holonym)",
    "%p": "部件整体 (Part Holonym)",
    "=":  "属性 (Attribute)",
    "+":  "派生关系 (Derivation)",
    ";c": "领域-类别 (Domain Category)",
    ";r": "领域-区域 (Domain Region)",
    ";u": "领域-用法 (Domain Usage)",
    "-c": "属于类别领域 (Domain Member Cat)",
    "-r": "属于区域领域 (Domain Member Reg)",
    "-u": "属于用法领域 (Domain Member Usage)",
    "^":  "参见 (Also See)",
    "&":  "相似 (Similar To)",
    "\\": "关联名词 (Pertainym)",
    "<":  "动词分词 (Participle)",
    "*":  "蕴含 (Entailment)",
    ">":  "致使 (Cause)",
    "$":  "动词组 (Verb Group)",
}

POS_TO_NAME = {"n": "名词", "v": "动词", "a": "形容词", "r": "副词"}
POS_TO_FILE = {"n": "noun", "v": "verb", "a": "adj", "r": "adv"}
POS_FILES = list(POS_TO_FILE.keys())


# ─────────────────────────── 数据类 ───────────────────────────

@dataclass
class Pointer:
    symbol: str
    pos: str
    target_offset: str
    source_w_num: int  # 0 = synset-level
    target_w_num: int  # 0 = synset-level


@dataclass
class Synset:
    offset: str
    pos: str
    lex_filenum: str
    ss_type: str
    words: List[Tuple[str, int]]          # (lemma, lex_id)
    pointers: List[Pointer] = field(default_factory=list)
    gloss: str = ""
    frames: List[int] = field(default_factory=list)  # 仅动词

    @property
    def synset_id(self) -> str:
        return f"{self.offset}{self.pos}"

    @property
    def word_list(self) -> str:
        return ", ".join(w[0] for w in self.words)


@dataclass
class IndexEntry:
    lemma: str
    pos: str
    synset_cnt: int
    ptr_symbols: List[str]
    offsets: List[str]
    tagged_sense_cnt: int


@dataclass
class SenseInfo:
    sense_key: str
    offset: str
    pos: str
    sense_number: int
    tag_cnt: int


@dataclass
class FrameText:
    frame_number: int
    frame_text: str


# ─────────────────────────── 解析器 ───────────────────────────

class WordNetDB:
    """内存级 WordNet 数据库"""

    def __init__(self, dict_dir: Path):
        self.dict_dir = dict_dir

        # 核心索引
        self.index: Dict[str, IndexEntry] = {}          # "lemma:pos" -> IndexEntry
        self.synsets: Dict[str, Synset] = {}            # "offset+pos" -> Synset
        self.senses: Dict[str, SenseInfo] = {}          # sense_key -> SenseInfo
        self.cntlist: Dict[str, Tuple[int, int]] = {}   # sense_key -> (count, rank)

        # 辅助数据
        self.exc: Dict[str, Dict[str, str]] = {p: {} for p in POS_FILES}  # pos -> {surface: base}
        self.frames: Dict[int, str] = {}                 # frame_number -> text
        self.sentidx: Dict[str, List[int]] = {}         # sense_key -> [sentence_nums]
        self.sents: Dict[int, str] = {}                  # sentence_num -> text

        self._load_all()

    # ── 加载入口 ──
    def _load_all(self):
        for pos in POS_FILES:
            self._load_index(pos)
            self._load_data(pos)
        self._load_sense_index()
        self._load_cntlist()
        self._load_exc()
        self._load_verb_frames()
        self._load_verb_examples()
        print(f"[加载完成] {len(self.synsets)} synsets, {len(self.index)} index entries, {len(self.senses)} senses", file=sys.stderr)

    # ── index.* ──
    def _load_index(self, pos: str):
        path = self.dict_dir / f"index.{POS_TO_FILE[pos]}"
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("  ") or not line.strip() or line.startswith("This"):
                    continue
                parts = line.strip().split()
                # 格式: lemma pos synset_cnt p_cnt [ptr_symbols...] sense_cnt tagsense_cnt [offsets...]
                lemma = parts[0]
                p_idx = 2
                synset_cnt = int(parts[p_idx])
                p_idx += 1
                ptr_cnt = int(parts[p_idx])
                p_idx += 1
                ptr_symbols = parts[p_idx : p_idx + ptr_cnt]
                p_idx += ptr_cnt
                sense_cnt = int(parts[p_idx])
                p_idx += 1
                tagged_sense_cnt = int(parts[p_idx])
                p_idx += 1
                offsets = parts[p_idx : p_idx + synset_cnt]
                key = f"{lemma}:{pos}"
                self.index[key] = IndexEntry(lemma, pos, synset_cnt, ptr_symbols, offsets, tagged_sense_cnt)

    # ── data.* ──
    def _load_data(self, pos: str):
        path = self.dict_dir / f"data.{POS_TO_FILE[pos]}"
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip() or line.startswith("  ") or line.startswith("This"):
                    continue
                self._parse_data_line(line.strip(), pos)

    def _parse_data_line(self, line: str, pos: str):
        # offset lex_filenum ss_type w_cnt word lex_id ... p_cnt ptr... | gloss
        head, _, gloss = line.partition(" | ")
        if not gloss:
            return  # 可能是异常行（无gloss，如某些特殊情况）

        parts = head.split()
        offset = parts[0]
        lex_filenum = parts[1]
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
            sym = parts[idx]
            t_offset = parts[idx + 1]
            t_pos = parts[idx + 2]
            # source/target word numbers encoded as 4 hex digits: ssxx + ttww
            hex_str = parts[idx + 3]
            src = int(hex_str[:2], 16) if len(hex_str) >= 4 else 0
            tgt = int(hex_str[2:4], 16) if len(hex_str) >= 4 else 0
            pointers.append(Pointer(sym, t_pos, t_offset, src, tgt))
            idx += 4

        # 动词特有的句法框架
        frames = []
        if pos == "v" and idx < len(parts):
            # 格式: f_cnt [+ frame_id [+ frame_id ...]]
            # 实际上格式是：f_cnt [+ frame_id + frame_id ...]
            # 注意 parts 中可能以 '+' 作为分隔符
            # 重新解析：在指针后面，frame 数据以 "+" 开头
            # 先还原原始 line 来解析末尾
            pass  # 下面用原始 line 重新解析 frames

        # 更可靠的 frame 解析：从原始 line 中提取
        if pos == "v":
            # 找到 gloss 之前最后一个非指针字段
            # frame 格式出现在 | 之前，以 "+" 为分隔符
            # 示例: ... 02 + 02 00 + 08 00 | gloss
            pre_gloss = line.split(" | ")[0]
            # frame 数据格式: [f_cnt] (+ frame_num w_num)*
            # 先检查末尾是否有 "+" 模式
            frame_match = re.findall(r'\+\s*(\d+)\s+(\d+)', pre_gloss)
            for m in frame_match:
                frames.append(int(m[0]))

        synset = Synset(offset, pos, lex_filenum, ss_type, words, pointers, gloss, frames)
        self.synsets[synset.synset_id] = synset

    # ── index.sense ──
    def _load_sense_index(self):
        path = self.dict_dir / "index.sense"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) < 4:
                    continue
                sense_key = parts[0]
                offset = parts[1]
                # 从 sense_key 解析 pos
                # format: lemma%ss_type:lex_filenum:lex_id[:head_word:head_id]
                m = re.search(r'%(\d+)', sense_key)
                if m:
                    ss_type_num = int(m.group()[1:])
                    pos = {1: "n", 2: "v", 3: "a", 4: "r", 5: "s"}.get(ss_type_num, "n")
                else:
                    pos = "n"
                sense_number = int(parts[2])
                tag_cnt = int(parts[3])
                self.senses[sense_key] = SenseInfo(sense_key, offset, pos, sense_number, tag_cnt)

    # ── cntlist ──
    def _load_cntlist(self):
        path = self.dict_dir / "cntlist"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for rank, line in enumerate(f, 1):
                parts = line.strip().split()
                if len(parts) < 3:
                    continue
                count = int(parts[0])
                sense_key = parts[1]
                self.cntlist[sense_key] = (count, rank)

    # ── *.exc ──
    def _load_exc(self):
        for pos in POS_FILES:
            path = self.dict_dir / f"{POS_TO_FILE[pos]}.exc"
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        surface = parts[0]
                        base = parts[1]
                        self.exc[pos][surface] = base

    # ── verb.Framestext ──
    def _load_verb_frames(self):
        path = self.dict_dir / "verb.Framestext"
        if not path.exists():
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2:
                    self.frames[int(parts[0])] = parts[1].strip()

    # ── sentidx.vrb + sents.vrb ──
    def _load_verb_examples(self):
        # sents.vrb
        sents_path = self.dict_dir / "sents.vrb"
        if sents_path.exists():
            with open(sents_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    m = re.match(r'(\d+)\s+(.*)', line)
                    if m:
                        self.sents[int(m.group(1))] = m.group(2)

        # sentidx.vrb
        idx_path = self.dict_dir / "sentidx.vrb"
        if idx_path.exists():
            with open(idx_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        sense_key = parts[0]
                        nums = [int(x.strip()) for x in parts[1].split(",")]
                        self.sentidx[sense_key] = nums

    # ─────────────────────────── 查询 API ───────────────────────────

    def lookup(self, word: str, pos_filter: Optional[str] = None) -> List[dict]:
        """
        查询一个单词在所有词性中的完整信息。
        如果 pos_filter 指定了 'n'/'v'/'a'/'r'，则只查该词性。
        返回每个 sense 的完整信息字典列表。
        """
        word = word.lower().replace(" ", "_")
        results = []

        poses = [pos_filter] if pos_filter else POS_FILES

        for pos in poses:
            key = f"{word}:{pos}"
            entry = self.index.get(key)
            if not entry:
                continue

            for offset in entry.offsets:
                synset = self.synsets.get(f"{offset}{pos}")
                if not synset:
                    continue
                results.append(self._build_result(entry, synset))

        return results

    def _build_result(self, entry: IndexEntry, synset: Synset) -> dict:
        """将一个 synset 打包为包含所有引用信息的字典。"""
        # 找到当前词在当前 synset 中的 sense_key
        sense_key = self._find_sense_key(entry.lemma, synset)
        sense_info = self.senses.get(sense_key) if sense_key else None

        # 词频
        freq = None
        if sense_key and sense_key in self.cntlist:
            cnt, rank = self.cntlist[sense_key]
            freq = {"count": cnt, "rank": rank}

        # 例句（仅动词）
        examples = []
        if synset.pos == "v" and sense_key:
            nums = self.sentidx.get(sense_key, [])
            for num in nums:
                text = self.sents.get(num)
                if text:
                    examples.append({"id": num, "text": text.replace("%s", entry.lemma)})

        # 句法框架（仅动词）
        frames = []
        for fn in synset.frames:
            ft = self.frames.get(fn)
            if ft:
                frames.append({"frame_id": fn, "frame": ft})

        # 解析指针 -> 按类型分组，每个包含目标信息
        pointers_by_type: Dict[str, List[dict]] = {}
        for ptr in synset.pointers:
            desc = POINTER_DESC.get(ptr.symbol, ptr.symbol)
            target = self.synsets.get(f"{ptr.target_offset}{ptr.pos}")
            target_info = None
            if target:
                target_info = {
                    "offset": ptr.target_offset,
                    "pos": ptr.pos,
                    "ss_type": SS_TYPE_MAP.get(ptr.pos, ptr.pos),
                    "words": target.word_list,
                    "gloss": target.gloss,
                }
            else:
                target_info = {
                    "offset": ptr.target_offset,
                    "pos": ptr.pos,
                    "ss_type": SS_TYPE_MAP.get(ptr.pos, ptr.pos),
                    "words": "(未加载)",
                    "gloss": "",
                }

            ptr_entry = {
                "symbol": ptr.symbol,
                "description": desc,
                "source_word": synset.words[ptr.source_w_num - 1][0] if ptr.source_w_num > 0 and ptr.source_w_num <= len(synset.words) else None,
                "target_word": target.words[ptr.target_w_num - 1][0] if target and ptr.target_w_num > 0 and ptr.target_w_num <= len(target.words) else None,
                "target": target_info,
            }
            pointers_by_type.setdefault(desc, []).append(ptr_entry)

        # 找到当前词在 synset 中的 lex_id
        current_lex_id = None
        for w, lid in synset.words:
            if w == entry.lemma:
                current_lex_id = lid
                break

        result = {
            "lemma": entry.lemma,
            "pos": synset.pos,
            "pos_name": SS_TYPE_MAP.get(synset.pos, synset.pos),
            "synset_id": synset.synset_id,
            "offset": synset.offset,
            "lex_filenum": synset.lex_filenum,
            "ss_type": synset.ss_type,
            "gloss": synset.gloss,
            "words": [{"word": w, "lex_id": lid} for w, lid in synset.words],
            "current_word": {
                "lemma": entry.lemma,
                "lex_id": current_lex_id,
                "sense_key": sense_key,
                "sense_number": sense_info.sense_number if sense_info else None,
                "tag_count": sense_info.tag_cnt if sense_info else None,
            },
            "frequency": freq,
            "pointers": pointers_by_type,
            "frames": frames,
            "examples": examples,
        }
        return result

    def _find_sense_key(self, lemma: str, synset: Synset) -> Optional[str]:
        """根据 lemma 和 synset 找到对应的 sense_key"""
        # 尝试匹配 index.sense 中的记录
        for sk, si in self.senses.items():
            if si.offset == synset.offset and si.pos == synset.pos:
                # sense_key 的 lemma 部分可能与 entry.lemma 略有不同（如大小写/替换）
                sk_lemma = sk.split("%")[0]
                if sk_lemma.lower() == lemma.lower():
                    return sk
        # 尝试构造 sense_key（如果不在 index.sense 中）
        # 但这需要 lex_id，可以从 synset.words 中找到
        return None

    def get_morph_exceptions(self, word: str) -> Dict[str, str]:
        """获取一个词的例外形态映射（正向+反向查找）"""
        word = word.lower().replace(" ", "_")
        results = {}
        for pos, mapping in self.exc.items():
            # surface -> base 正向
            if word in mapping:
                results[pos] = mapping[word]
            # base -> surfaces 反向
            for surface, base in mapping.items():
                if base == word:
                    results.setdefault(f"{pos}_from", []).append(surface)
        return results


# ─────────────────────────── 格式化输出 ───────────────────────────

def print_result(result: dict, db: WordNetDB):
    """以人类友好的方式打印单个 sense 的完整信息。"""
    lemma = result["lemma"]
    pos_name = result["pos_name"]
    offset = result["offset"]
    gloss = result["gloss"]

    print()
    print("=" * 70)
    header = f"  {lemma}  [{pos_name}]  (offset: {offset})"
    print(header)
    print("=" * 70)

    # 基本信息
    print(f"\n【词形】")
    print(f"  lemma: {lemma}")
    print(f"  pos:   {result['pos']} ({pos_name})")
    print(f"  ss_type: {result['ss_type']} ({SS_TYPE_MAP.get(result['ss_type'], '未知')})")
    print(f"  lex_file: {result['lex_filenum']}")

    # 同义词
    print(f"\n【同义词集 Synset】")
    words_str = "  |  ".join(f"{w['word']} (lex_id={w['lex_id']})" for w in result["words"])
    print(f"  {words_str}")

    # 当前词的 sense 信息
    cw = result["current_word"]
    print(f"\n【当前 Sense】")
    print(f"  sense_key:    {cw['sense_key'] or '(构造失败)'}")
    print(f"  sense_number: {cw['sense_number']}")
    print(f"  lex_id:       {cw['lex_id']}")
    print(f"  tag_count:    {cw['tag_count']}")

    # 词频
    if result["frequency"]:
        f = result["frequency"]
        print(f"\n【语料频率】")
        print(f"  count: {f['count']}")
        print(f"  rank:  #{f['rank']}")

    # 定义
    print(f"\n【定义 (Gloss)】")
    print(f"  {gloss}")

    # 句法框架（仅动词）
    if result["frames"]:
        print(f"\n【句法框架】")
        for fr in result["frames"]:
            print(f"  [{fr['frame_id']:02d}] {fr['frame']}")

    # 例句（仅动词）
    if result["examples"]:
        print(f"\n【例句】")
        for ex in result["examples"]:
            print(f"  [{ex['id']:03d}] {ex['text']}")

    # 关系指针
    if result["pointers"]:
        print(f"\n【语义关系 (Pointers)】")
        for ptype, ptrs in result["pointers"].items():
            print(f"\n  ▸ {ptype}")
            for p in ptrs:
                src = f" (src={p['source_word']})" if p["source_word"] else ""
                tgt_w = f" (tgt_word={p['target_word']})" if p["target_word"] else ""
                ti = p["target"]
                print(f"    → [{ti['offset']}{ti['pos']}] {ti['words']}{src}{tgt_w}")
                if ti["gloss"]:
                    gloss_short = ti["gloss"][:80] + "..." if len(ti["gloss"]) > 80 else ti["gloss"]
                    print(f"      └─ {gloss_short}")

    # 关系递归：显示一级上位/下位/部分/整体 的完整上下文
    print(f"\n【关系网络 (1-hop)】")
    _print_relation_network(result, db)

    print()


def _print_relation_network(result: dict, db: WordNetDB):
    """打印当前 synset 的一跳关系网络摘要。"""
    synset_id = result["synset_id"]
    synset = db.synsets.get(synset_id)
    if not synset:
        return

    # 上位词链 (向上递归一层)
    hypernyms = [p for p in synset.pointers if p.symbol in ("@", "@i")]
    if hypernyms:
        print(f"  ▲ 上位词 (Hypernyms):")
        for p in hypernyms:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                print(f"      {target.word_list}")
                print(f"      └─ {target.gloss[:100]}...")

    # 下位词
    hyponyms = [p for p in synset.pointers if p.symbol in ("~", "~i")]
    if hyponyms:
        print(f"  ▼ 下位词 (Hyponyms) [{len(hyponyms)} 个]:")
        for p in hyponyms[:10]:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                print(f"      [{p.target_offset}{p.pos}] {target.word_list}")
        if len(hyponyms) > 10:
            print(f"      ... 还有 {len(hyponyms) - 10} 个")

    # 反义词
    ants = [p for p in synset.pointers if p.symbol == "!"]
    if ants:
        print(f"  ◆ 反义词 (Antonyms):")
        for p in ants:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                print(f"      {target.word_list}")

    # 部分-整体
    meronyms = [p for p in synset.pointers if p.symbol.startswith("#")]
    if meronyms:
        print(f"  ◈ 部分关系 (Meronyms) [{len(meronyms)}]:")
        for p in meronyms[:5]:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                print(f"      {POINTER_DESC.get(p.symbol, p.symbol)}: {target.word_list}")

    holonyms = [p for p in synset.pointers if p.symbol.startswith("%")]
    if holonyms:
        print(f"  ◈ 整体关系 (Holonyms) [{len(holonyms)}]:")
        for p in holonyms[:5]:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                print(f"      {POINTER_DESC.get(p.symbol, p.symbol)}: {target.word_list}")

    # 派生关系
    derivs = [p for p in synset.pointers if p.symbol == "+"]
    if derivs:
        print(f"  ◇ 派生关系 (Derivations) [{len(derivs)}]:")
        for p in derivs:
            target = db.synsets.get(f"{p.target_offset}{p.pos}")
            if target:
                src_w = f"{p.source_w_num}:{synset.words[p.source_w_num-1][0]}" if p.source_w_num > 0 else "synset"
                tgt_w = f"{p.target_w_num}:{target.words[p.target_w_num-1][0]}" if p.target_w_num > 0 else "synset"
                print(f"      {src_w} → {tgt_w}  [{target.word_list}]")

    # 动词特有
    if synset.pos == "v":
        entails = [p for p in synset.pointers if p.symbol == "*"]
        if entails:
            print(f"  ◊ 蕴含 (Entailments):")
            for p in entails:
                target = db.synsets.get(f"{p.target_offset}{p.pos}")
                if target:
                    print(f"      {target.word_list}")
        causes = [p for p in synset.pointers if p.symbol == ">"]
        if causes:
            print(f"  ◊ 致使 (Causes):")
            for p in causes:
                target = db.synsets.get(f"{p.target_offset}{p.pos}")
                if target:
                    print(f"      {target.word_list}")


def print_morph_info(word: str, db: WordNetDB):
    """打印形态学例外信息。"""
    info = db.get_morph_exceptions(word)
    if not info:
        return
    print(f"\n【形态学例外 (Morphological Exceptions)】")
    for k, v in info.items():
        pos = k.replace("_from", "")
        if k.endswith("_from"):
            print(f"  {POS_TO_NAME.get(pos, pos)}: {word} ← 来自: {', '.join(v)}")
        else:
            print(f"  {POS_TO_NAME.get(k, k)}: {word} → 原形: {v}")


# ─────────────────────────── 交互入口 ───────────────────────────

def interactive(db: WordNetDB):
    print("=" * 70)
    print("  WordNet 3.1 查询工具")
    print("  命令: <word> [n|v|a|r]    例: dog n | run v | happy a")
    print("        q / quit / exit     退出")
    print("=" * 70)

    while True:
        try:
            raw = input("\nwn> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            break

        parts = raw.split()
        word = parts[0]
        pos_filter = parts[1] if len(parts) > 1 and parts[1] in POS_FILES else None

        results = db.lookup(word, pos_filter)
        if not results:
            print(f"  未找到 '{word}'" + (f" [{POS_TO_NAME.get(pos_filter, pos_filter)}]" if pos_filter else ""))
            # 尝试例外形态查找
            found_via_exc = False
            for p in POS_FILES:
                if pos_filter and p != pos_filter:
                    continue
                base = db.exc[p].get(word.lower())
                if base:
                    print(f"  但通过 {p}.exc 找到例外形态 '{word}' → 原形 '{base}'")
                    results = db.lookup(base, p)
                    found_via_exc = True
                    break
            if not found_via_exc:
                continue

        print(f"\n  共找到 {len(results)} 个 sense(s)")
        for r in results:
            print_result(r, db)
            print_morph_info(r["lemma"], db)


def main():
    # 强制 UTF-8 输出（解决 Windows GBK 编码问题）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    print("[正在加载 WordNet 3.1 数据库...]")
    db = WordNetDB(DICT_DIR)
    interactive(db)
    print("再见!")


if __name__ == "__main__":
    main()
