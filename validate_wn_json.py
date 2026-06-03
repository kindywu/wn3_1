"""用 wn-json-schema-1.4.json 校验 english-wordnet-2025-json 目录下的 JSON 文件。

文件使用 compact 格式（与 schema 描述的 normalized WN-JSON 格式不同）：
  - partOfSpeech 是短码 (n/v/a/r/s) 而非全名 (noun/verb/adjective/adverb/adjective_satellite)
  - definition 是字符串数组而非 {gloss, ...} 对象数组
  - example 是字符串或 {text, source?} 对象数组，而不是 schema 的 {value, ...} 对象数组
  - 关系类型是内联属性 (hypernym/similar 等) 而非统一的 relations 数组
  - synset 文件以 synset_id 为 key，entry 文件以 lemma→pos 嵌套

本脚本从 schema 提取合法值集合，映射到 compact 格式后做语义验证，
并报告 compact 格式与 schema 之间的结构性偏离。
"""

import json
import re
import sys
from pathlib import Path

# ── schema → compact 映射 ─────────────────────────────────────────────

# schema partOfSpeech → compact 短码
POS_FULL_TO_SHORT: dict[str, str] = {
    "noun": "n",
    "verb": "v",
    "adjective": "a",
    "adjective_satellite": "s",
    "adverb": "r",
    "phrase": "phrase",
    "conjunction": "conjunction",
    "adposition": "adposition",
    "other": "other",
    "unknown": "unknown",
}
VALID_POS: set[str] = set(POS_FULL_TO_SHORT.values())

# schema 中 synset-level 关系类型
SYNSET_REL_TYPES: set[str] = {
    "agent",
    "also",
    "attribute",
    "be_in_state",
    "causes",
    "classified_by",
    "classifies",
    "co_agent_instrument",
    "co_agent_patient",
    "co_agent_result",
    "co_instrument_agent",
    "co_instrument_patient",
    "co_instrument_result",
    "co_patient_agent",
    "co_patient_instrument",
    "co_result_agent",
    "co_result_instrument",
    "co_role",
    "direction",
    "domain_region",
    "domain_topic",
    "exemplifies",
    "entails",
    "eq_synonym",
    "has_domain_region",
    "has_domain_topic",
    "is_exemplified_by",
    "holo_location",
    "holo_member",
    "holo_part",
    "holo_portion",
    "holo_substance",
    "holonym",
    "hypernym",
    "hyponym",
    "in_manner",
    "instance_hypernym",
    "instance_hyponym",
    "instrument",
    "involved",
    "involved_agent",
    "involved_direction",
    "involved_instrument",
    "involved_location",
    "involved_patient",
    "involved_result",
    "involved_source_direction",
    "involved_target_direction",
    "is_caused_by",
    "is_entailed_by",
    "location",
    "manner_of",
    "mero_location",
    "mero_member",
    "mero_part",
    "mero_portion",
    "mero_substance",
    "meronym",
    "similar",
    "other",
    "patient",
    "restricted_by",
    "restricts",
    "result",
    "role",
    "source_direction",
    "state_of",
    "target_direction",
    "subevent",
    "is_subevent_of",
    "antonym",
}

# schema 中 sense-level 关系类型
SENSE_REL_TYPES: set[str] = {
    "antonym",
    "also",
    "participle",
    "pertainym",
    "derivation",
    "domain_topic",
    "has_domain_topic",
    "domain_region",
    "has_domain_region",
    "exemplifies",
    "is_exemplified_by",
    "similar",
    "metaphor",
    "has_metaphor",
    "metonym",
    "has_metonym",
    "agent",
    "material",
    "event",
    "instrument",
    "location",
    "by_means_of",
    "undergoer",
    "property",
    "result",
    "state",
    "uses",
    "destination",
    "body_part",
    "vehicle",
    "other",
}

# compact 格式中 synset 对象允许出现的字段（除关系类型外）
SYNSET_KNOWN_FIELDS: set[str] = {
    "partOfSpeech",
    "definition",
    "example",
    "ili",
    "members",
    "iliDefinition",
    "lexfile",
    "value",
    "status",
    "confidenceScore",
    "contributor",
    "coverage",
    "creator",
    "date",
    "description",
    "format",
    "identifier",
    "publisher",
    "relation",
    "source",
    "rights",
    "subject",
    "title",
    "type",
    "wikidata",
}

# compact 格式中 entry/pos 对象允许出现的字段
ENTRY_KNOWN_FIELDS: set[str] = {
    "pronunciation",
    "sense",
    "synBehavior",
    "form",
    "tag",
    "status",
    "confidenceScore",
    "contributor",
    "coverage",
    "creator",
    "date",
    "description",
    "format",
    "identifier",
    "publisher",
    "relation",
    "source",
    "subject",
    "title",
    "type",
    "index",
}

# synset_id 合法格式: 8位数字-pos
SYNSET_ID_RE = re.compile(r"^\d{8}-[nvars]$")

# synsetRef 合法格式: 8位数字-pos
SYNSET_REF_RE = re.compile(r"^\d{8}-[nvars]$")

# ── 全局统计计数器 ─────────────────────────────────────────────────────


class Stats:
    def __init__(self):
        self.dict_examples = 0  # {text, source?} 格式的 example 个数
        self.errors: list[str] = []


_stats = Stats()


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── 底层校验辅助 ──────────────────────────────────────────────────────


def _is_str(v) -> bool:
    return isinstance(v, str)


def _check_example_item(value, label: str) -> str | None:
    """校验 example 数组中的单个元素。

    接受两种 compact 格式：
      - 字符串（主流）
      - {text: str, source?: str}（带引用的例句）
    schema 格式是 {value: str, ...}，与 compact 不同，此处仅记录统计。
    """
    if isinstance(value, str):
        return None
    if isinstance(value, dict):
        if "text" not in value:
            return f"[{label}] 缺少 text 字段"
        if not isinstance(value["text"], str):
            return f"[{label}].text 期望 string，实际 {type(value['text']).__name__}"
        if "source" in value and not isinstance(value["source"], str):
            return (
                f"[{label}].source 期望 string，实际 {type(value['source']).__name__}"
            )
        _stats.dict_examples += 1
        return None
    return f"[{label}] 期望 string 或 {{text, source?}} object，实际 {type(value).__name__}"


def _check_str_list(value, label: str, allow_empty: bool = False) -> str | None:
    """校验纯字符串数组。"""
    if not isinstance(value, list):
        return f"[{label}] 期望 array，实际 {type(value).__name__}"
    if not allow_empty and len(value) == 0:
        return f"[{label}] 数组不能为空"
    for i, item in enumerate(value):
        if not isinstance(item, str):
            return f"[{label}[{i}]] 期望 string，实际 {type(item).__name__}"
    return None


def _check_example_list(value, label: str) -> str | None:
    """校验 example 数组（元素可以是 string 或 {text, source?} object）。"""
    if not isinstance(value, list):
        return f"[{label}] 期望 array，实际 {type(value).__name__}"
    if len(value) == 0:
        return f"[{label}] 数组不能为空"
    for i, item in enumerate(value):
        err = _check_example_item(item, f"{label}[{i}]")
        if err:
            return err
    return None


# ── 校验函数 ──────────────────────────────────────────────────────────


def validate_synset_file(path: Path) -> list[str]:
    """校验 synset 文件（noun.*.json, verb.*.json, adj.*.json, adv.*.json）。

    格式: {"synset_id": {partOfSpeech, definition, members, ...}}
    """
    data = load_json(path)
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"{path.name}: 顶层期望 object，实际 {type(data).__name__}"]

    for sid, item in data.items():
        ctx = f"{path.name}:{sid}"

        # synset_id 格式
        if not SYNSET_ID_RE.fullmatch(sid):
            errors.append(f"{ctx}: synset_id 格式非法（期望 8位数字-pos）")

        if not isinstance(item, dict):
            errors.append(f"{ctx}: 期望 object，实际 {type(item).__name__}")
            continue

        # partOfSpeech（必填）
        pos = item.get("partOfSpeech")
        if pos is None:
            errors.append(f"{ctx}: 缺少 partOfSpeech")
        elif pos not in VALID_POS:
            errors.append(
                f"{ctx}: partOfSpeech={pos!r} 不在合法值 {sorted(VALID_POS)} 中"
            )

        # members（必填，非空字符串数组）
        if "members" not in item:
            errors.append(f"{ctx}: 缺少 members")
        else:
            err = _check_str_list(item["members"], f"{ctx}.members")
            if err:
                errors.append(err)

        # definition（必填，非空字符串数组）
        if "definition" not in item:
            errors.append(f"{ctx}: 缺少 definition")
        else:
            err = _check_str_list(item["definition"], f"{ctx}.definition")
            if err:
                errors.append(err)

        # example（可选，字符串或 {text, source?} 对象数组）
        if "example" in item:
            err = _check_example_list(item["example"], f"{ctx}.example")
            if err:
                errors.append(err)

        # ili（可选，string）
        if "ili" in item:
            if not isinstance(item["ili"], str):
                errors.append(
                    f"{ctx}.ili: 期望 string，实际 {type(item['ili']).__name__}"
                )
            elif not item["ili"].startswith("i"):
                errors.append(f"{ctx}.ili: ili 应以 'i' 开头，实际 {item['ili']!r}")

        # iliDefinition（可选，object with gloss）
        if "iliDefinition" in item:
            idef = item["iliDefinition"]
            if not isinstance(idef, dict):
                errors.append(f"{ctx}.iliDefinition: 期望 object")
            elif "gloss" not in idef:
                errors.append(f"{ctx}.iliDefinition: 缺少 gloss")
            elif not isinstance(idef.get("gloss"), str):
                errors.append(f"{ctx}.iliDefinition.gloss: 期望 string")

        # 关系属性: 必须是字符串数组
        for rel in SYNSET_REL_TYPES:
            if rel in item:
                err = _check_str_list(item[rel], f"{ctx}.{rel}")
                if err:
                    errors.append(err)

        # 检查未知字段
        allowed = SYNSET_KNOWN_FIELDS | SYNSET_REL_TYPES
        for key in item:
            if key not in allowed:
                errors.append(f"{ctx}: 未知字段 {key!r}")

    return errors


def validate_entry_file(path: Path) -> list[str]:
    """校验 entry 文件（entries-a.json ~ entries-z.json）。

    格式: {"lemma": {"pos": {sense: [...], pronunciation: [...]}}}
    """
    data = load_json(path)
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"{path.name}: 顶层期望 object，实际 {type(data).__name__}"]

    for lemma, pos_map in data.items():
        if not isinstance(pos_map, dict):
            errors.append(
                f"{path.name}:{lemma}: 期望 object，实际 {type(pos_map).__name__}"
            )
            continue

        for pos, item in pos_map.items():
            ctx = f"{path.name}:{lemma}/{pos}"

            if pos not in VALID_POS:
                # 允许带数字后缀的 homonym disambiguator（如 n-1, n-2, v-1, a-1）
                base_pos = pos.rsplit("-", 1)[0] if "-" in pos else pos
                if base_pos not in VALID_POS:
                    errors.append(
                        f"{ctx}: pos={pos!r} 不在合法值 {sorted(VALID_POS)} 中"
                    )

            if not isinstance(item, dict):
                errors.append(f"{ctx}: 期望 object，实际 {type(item).__name__}")
                continue

            # sense（可选但如果有必须是非空数组）
            if "sense" in item:
                senses = item["sense"]
                if not isinstance(senses, list):
                    errors.append(f"{ctx}.sense: 期望 array")
                elif len(senses) == 0:
                    errors.append(f"{ctx}.sense: 数组不能为空")
                else:
                    for i, s in enumerate(senses):
                        sctx = f"{ctx}.sense[{i}]"
                        if not isinstance(s, dict):
                            errors.append(f"{sctx}: 期望 object")
                            continue

                        synset = s.get("synset")
                        if synset is None:
                            errors.append(f"{sctx}: 缺少 synset")
                        elif not isinstance(synset, str):
                            errors.append(f"{sctx}.synset: 期望 string")
                        elif not SYNSET_REF_RE.fullmatch(synset):
                            errors.append(
                                f"{sctx}.synset={synset!r}: 格式应为 8位数字-pos"
                            )

                        sid_val = s.get("id")
                        if sid_val is not None:
                            if not isinstance(sid_val, str):
                                errors.append(f"{sctx}.id: 期望 string")
                            elif "%" not in sid_val:
                                errors.append(
                                    f"{sctx}.id={sid_val!r}: 格式非法（缺少 %）"
                                )

                        # sense relations
                        for rel in SENSE_REL_TYPES:
                            if rel in s:
                                err = _check_str_list(s[rel], f"{sctx}.{rel}")
                                if err:
                                    errors.append(err)

                        # example in sense
                        if "example" in s:
                            err = _check_example_list(s["example"], f"{sctx}.example")
                            if err:
                                errors.append(err)

                        # 检查未知字段
                        sense_allowed = {
                            "id",
                            "synset",
                            "n",
                            "subcat",
                            "relations",
                            "example",
                            "count",
                            "status",
                            "confidenceScore",
                            "contributor",
                            "coverage",
                            "creator",
                            "date",
                            "description",
                            "format",
                            "identifier",
                            "publisher",
                            "relation",
                            "source",
                            "subject",
                            "title",
                            "type",
                            "sent",
                            "adjposition",
                        } | SENSE_REL_TYPES
                        for key in s:
                            if key not in sense_allowed:
                                errors.append(f"{sctx}: 未知字段 {key!r}")

            # pronunciation（可选，非空数组）
            if "pronunciation" in item:
                prons = item["pronunciation"]
                if not isinstance(prons, list):
                    errors.append(f"{ctx}.pronunciation: 期望 array")
                elif len(prons) == 0:
                    errors.append(f"{ctx}.pronunciation: 数组不能为空")
                else:
                    for i, p in enumerate(prons):
                        pctx = f"{ctx}.pronunciation[{i}]"
                        if not isinstance(p, dict):
                            errors.append(f"{pctx}: 期望 object")
                        elif "value" not in p:
                            errors.append(f"{pctx}: 缺少 value")
                        elif not isinstance(p.get("value"), str):
                            errors.append(f"{pctx}.value: 期望 string")

            # form（可选，非空数组，元素可以是 string 或 {writtenForm, ...} object）
            if "form" in item:
                forms = item["form"]
                if not isinstance(forms, list):
                    errors.append(f"{ctx}.form: 期望 array")
                elif len(forms) == 0:
                    errors.append(f"{ctx}.form: 数组不能为空")
                else:
                    for i, f in enumerate(forms):
                        fctx = f"{ctx}.form[{i}]"
                        if isinstance(f, str):
                            continue  # compact 格式允许纯字符串的变形
                        if not isinstance(f, dict):
                            errors.append(
                                f"{fctx}: 期望 string 或 object，实际 {type(f).__name__}"
                            )
                        elif "writtenForm" not in f:
                            errors.append(f"{fctx}: 缺少 writtenForm")
                        elif not isinstance(f.get("writtenForm"), str):
                            errors.append(f"{fctx}.writtenForm: 期望 string")

            # example at entry-level
            if "example" in item:
                err = _check_example_list(item["example"], f"{ctx}.example")
                if err:
                    errors.append(err)

            # 检查未知字段
            for key in item:
                if key not in ENTRY_KNOWN_FIELDS:
                    errors.append(f"{ctx}: 未知字段 {key!r}")

    return errors


def validate_frames_file(path: Path) -> list[str]:
    """校验 frames.json（string→string 映射）。"""
    data = load_json(path)
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{path.name}: 顶层期望 object，实际 {type(data).__name__}"]
    for key, value in data.items():
        if not isinstance(value, str):
            errors.append(
                f"{path.name}:{key}: 期望 string，实际 {type(value).__name__}"
            )
    return errors


# ── 入口 ──────────────────────────────────────────────────────────────


def main() -> None:
    schema_path = Path("asset/wn-json-schema-1.4.json")
    data_dir = Path("dict/english-wordnet-2025-json")

    if not schema_path.exists():
        print(f"错误: schema 文件不存在: {schema_path}")
        sys.exit(1)
    if not data_dir.exists():
        print(f"错误: 数据目录不存在: {data_dir}")
        sys.exit(1)

    json_files = sorted(data_dir.glob("*.json"))
    if not json_files:
        print(f"错误: {data_dir} 下没有 JSON 文件")
        sys.exit(1)

    total_errors = 0
    pass_count = 0
    fail_details: list[tuple[str, int]] = []

    for fp in json_files:
        name = fp.name
        if name.startswith("entries-"):
            errs = validate_entry_file(fp)
        elif name == "frames.json":
            errs = validate_frames_file(fp)
        else:
            errs = validate_synset_file(fp)

        if errs:
            fail_details.append((name, len(errs)))
            total_errors += len(errs)
            print(f"\n{'='*70}")
            print(f"FAIL  {name}  ({len(errs)} 个错误)")
            print(f"{'='*70}")
            for e in errs:
                print(f"  {e}")
        else:
            pass_count += 1

    # ── 汇总 ──
    print(f"\n{'='*70}")
    print(
        f"校验完成: {pass_count} 个文件通过, {len(fail_details)} 个文件失败 ({total_errors} 个错误)"
    )
    print(f"{'='*70}")

    # ── compact 格式与 schema 差异报告 ──
    print(f"\n--- compact 格式与 schema 1.4 的结构差异 ---")
    print(
        f"  partOfSpeech: compact 使用短码 (n/v/a/r/s)，schema 使用全名 (noun/verb/adjective/...)"
    )
    print(
        f"  definition:   compact 使用纯字符串数组，schema 使用 {{gloss, language, ...}} 对象数组"
    )
    print(f"  example:      compact 使用字符串或 {{text, source?}} 对象数组")
    print(f"                schema 使用 {{value, ...}} 对象数组")
    print(
        f"                (本批次发现 {_stats.dict_examples} 个 {{text, source?}} 格式的 example)"
    )
    print(
        f"  关系类型:     compact 使用内联属性 (hypernym/similar/...)，schema 使用 relations 数组"
    )
    print(f"  synset key:   compact 以 synset_id 为顶层 key，schema 以 @id 属性标识")
    print(f"  entry 结构:   compact 以 lemma→pos 嵌套，schema 以平铺的 entry 数组")

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
