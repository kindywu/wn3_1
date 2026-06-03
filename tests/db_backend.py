from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

MAIN_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(MAIN_DIR))
from main import POINTER_DESC, POS_FILES, SS_TYPE_MAP

sys.path.pop(0)


class DbWordNetDB:
    """基于 SQLite (db/wn.db) 的 WordNet 查询后端。

    设计上复用 main.py 的常量与输出结构，保证两端可直接对比。
    """

    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row

        # 内存缓存
        self._synsets: Dict[str, dict] = {}
        self._synset_words: Dict[str, List[Tuple[str, int]]] = {}
        self._pointers: Dict[str, List[dict]] = {}
        self._entries: Dict[Tuple[str, str], dict] = {}
        self._entry_senses: Dict[Tuple[str, str], List[dict]] = {}
        self._freq: Dict[int, Tuple[int, int]] = {}
        self._sense_frames: Dict[int, List[int]] = {}
        self._sense_examples: Dict[int, List[int]] = {}
        self._frames: Dict[int, str] = {}
        self._examples: Dict[int, str] = {}
        self._morph_exc: Dict[str, Dict[str, str]] = {}

        self._load_all()

    def _load_all(self):
        self._load_synsets()
        self._load_synset_words()
        self._load_pointers()
        self._load_entries()
        self._load_entry_senses()
        self._load_frequencies()
        self._load_sense_frames()
        self._load_sense_examples()
        self._load_frames()
        self._load_examples()
        self._load_morph_exceptions()

    # ── 预加载 ──

    def _load_synsets(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT synset_id, offset, pos, lex_filenum, ss_type, gloss "
            "FROM synset WHERE version='3.1'"
        ):
            self._synsets[row["synset_id"]] = {
                "synset_id": row["synset_id"],
                "offset": row["offset"],
                "pos": row["pos"],
                "lex_filenum": row["lex_filenum"],
                "ss_type": row["ss_type"],
                "gloss": row["gloss"],
            }

    def _load_synset_words(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT s.synset_id, e.lemma, s.lex_id, s.sense_number "
            "FROM sense s JOIN lexical_entry e ON s.entry_id=e.entry_id "
            "WHERE s.version='3.1' "
            "ORDER BY s.synset_id, s.sense_number, e.lemma"
        )
        for row in cur.fetchall():
            sid = row["synset_id"]
            self._synset_words.setdefault(sid, []).append((row["lemma"], row["lex_id"]))

    def _load_pointers(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT symbol, source_synset_id, target_synset_id, "
            "source_w_num, target_w_num "
            "FROM pointer WHERE version='3.1'"
        )
        for row in cur.fetchall():
            sid = row["source_synset_id"]
            self._pointers.setdefault(sid, []).append(
                {
                    "symbol": row["symbol"],
                    "target_synset_id": row["target_synset_id"],
                    "source_w_num": row["source_w_num"],
                    "target_w_num": row["target_w_num"],
                }
            )

    def _load_entries(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT entry_id, lemma, pos, synset_count, "
            "tagged_sense_count, pointer_symbols "
            "FROM lexical_entry WHERE version='3.1'"
        ):
            key = (row["lemma"], row["pos"])
            self._entries[key] = {
                "entry_id": row["entry_id"],
                "lemma": row["lemma"],
                "pos": row["pos"],
                "synset_count": row["synset_count"],
                "tagged_sense_count": row["tagged_sense_count"],
                "pointer_symbols": row["pointer_symbols"],
            }

    def _load_entry_senses(self):
        cur = self.conn.cursor()
        cur.execute(
            "SELECT s.sense_id, s.synset_id, s.entry_id, s.sense_key, "
            "s.sense_number, s.tag_cnt, s.lex_id, e.lemma, e.pos "
            "FROM sense s JOIN lexical_entry e ON s.entry_id=e.entry_id "
            "WHERE s.version='3.1' "
            "ORDER BY e.lemma, e.pos, s.sense_number"
        )
        for row in cur.fetchall():
            key = (row["lemma"], row["pos"])
            self._entry_senses.setdefault(key, []).append(
                {
                    "sense_id": row["sense_id"],
                    "synset_id": row["synset_id"],
                    "entry_id": row["entry_id"],
                    "sense_key": row["sense_key"],
                    "sense_number": row["sense_number"],
                    "tag_cnt": row["tag_cnt"],
                    "lex_id": row["lex_id"],
                    "lemma": row["lemma"],
                    "pos": row["pos"],
                }
            )

    def _load_frequencies(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT sense_id, count, rank FROM sense_frequency WHERE version='3.1'"
        ):
            self._freq[row["sense_id"]] = (row["count"], row["rank"])

    def _load_sense_frames(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT sense_id, frame_number FROM sense_frame WHERE version='3.1'"
        ):
            self._sense_frames.setdefault(row["sense_id"], []).append(
                row["frame_number"]
            )

    def _load_sense_examples(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT sense_id, sentence_number FROM sense_example WHERE version='3.1'"
        ):
            self._sense_examples.setdefault(row["sense_id"], []).append(
                row["sentence_number"]
            )

    def _load_frames(self):
        cur = self.conn.cursor()
        for row in cur.execute("SELECT frame_number, frame_text FROM syntactic_frame"):
            self._frames[row["frame_number"]] = row["frame_text"]

    def _load_examples(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT sentence_number, sentence_text FROM example_sentence"
        ):
            self._examples[row["sentence_number"]] = row["sentence_text"]

    def _load_morph_exceptions(self):
        cur = self.conn.cursor()
        for row in cur.execute(
            "SELECT pos, surface_form, base_form FROM morph_exception WHERE version='3.1'"
        ):
            self._morph_exc.setdefault(row["pos"], {})[row["surface_form"]] = row[
                "base_form"
            ]

    # ── 查询 API ──

    def lookup(self, word: str, pos_filter: Optional[str] = None) -> List[dict]:
        """查询单词，返回结构严格对齐 main.py 的 _build_result。"""
        word = word.lower().replace(" ", "_")
        results: List[dict] = []
        poses = [pos_filter] if pos_filter else POS_FILES

        for pos in poses:
            entry = self._entries.get((word, pos))
            if not entry:
                continue
            senses = self._entry_senses.get((entry["lemma"], pos), [])
            for sense in senses:
                synset = self._synsets.get(sense["synset_id"])
                if not synset:
                    continue
                results.append(self._build_result(entry, synset, sense))

        return results

    def _build_result(self, entry: dict, synset: dict, sense: dict) -> dict:
        """将 entry + synset + sense 打包为结果字典。"""
        words = self._synset_words.get(synset["synset_id"], [])

        current_word = {
            "lemma": entry["lemma"],
            "lex_id": sense["lex_id"],
            "sense_key": sense["sense_key"],
            "sense_number": sense["sense_number"],
            "tag_count": sense["tag_cnt"],
        }

        freq = self._freq.get(sense["sense_id"])
        freq_dict = {"count": freq[0], "rank": freq[1]} if freq else None

        # pointers
        pointers_by_type: Dict[str, List[dict]] = {}
        for ptr in self._pointers.get(synset["synset_id"], []):
            desc = POINTER_DESC.get(ptr["symbol"], ptr["symbol"])
            target_synset_id = ptr["target_synset_id"]
            target = self._synsets.get(target_synset_id)
            target_words = self._synset_words.get(target_synset_id, [])
            target_word_str = ", ".join(w[0] for w in target_words)

            target_info = {
                "offset": target_synset_id[:-1],
                "pos": target_synset_id[-1],
                "ss_type": SS_TYPE_MAP.get(target_synset_id[-1], target_synset_id[-1]),
                "words": target_word_str if target else "(未加载)",
                "gloss": target["gloss"] if target else "",
            }

            ptr_entry = {
                "symbol": ptr["symbol"],
                "description": desc,
                "source_word": None,
                "target_word": None,
                "source_w_num": ptr["source_w_num"],
                "target_w_num": ptr["target_w_num"],
                "target": target_info,
            }
            pointers_by_type.setdefault(desc, []).append(ptr_entry)

        # frames（按 sense_id）
        frames = []
        for fn in self._sense_frames.get(sense["sense_id"], []):
            ft = self._frames.get(fn)
            if ft:
                frames.append({"frame_id": fn, "frame": ft})

        # examples（按 sense_id）
        examples = []
        for num in self._sense_examples.get(sense["sense_id"], []):
            text = self._examples.get(num)
            if text:
                examples.append(
                    {
                        "id": num,
                        "text": text.replace("%s", entry["lemma"]),
                    }
                )

        return {
            "lemma": entry["lemma"],
            "pos": synset["pos"],
            "pos_name": SS_TYPE_MAP.get(synset["pos"], synset["pos"]),
            "synset_id": synset["synset_id"],
            "offset": synset["offset"],
            "lex_filenum": f"{synset['lex_filenum']:02d}",
            "ss_type": synset["ss_type"],
            "gloss": synset["gloss"],
            "words": [{"word": w[0], "lex_id": w[1]} for w in words],
            "current_word": current_word,
            "frequency": freq_dict,
            "pointers": pointers_by_type,
            "frames": frames,
            "examples": examples,
        }
