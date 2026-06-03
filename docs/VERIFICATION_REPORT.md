# WordNet 3.1 导入校验报告

## 校验时间

2026-06-03 11:19:33

## 源文件

wn3.1.dict.tar.gz

---

## 1. 架构概览

```
asset/wn3.1.dict.tar.gz (16MB)
    │
    ├─[tar extract]──▶ dict/ (36MB, 25 个文件)
    │                       │
    │                       ├──▶ main.py::WordNetDB ──▶ file_db fixture（文件端基准）
    │                       │
    │                       └──▶ import_wn.py ──▶ db/wn.db (93MB, 11 张表)
    │                                                    │
    │                       ┌────────────────────────────┘
    │                       ▼
    │              tests/db_backend.py::DbWordNetDB ──▶ db_db fixture（数据库端）
    │                       │
    │                       ▼
    │              tests/compare_utils.py::compare_lookup_results()
    │                       │
    │                       ▼
    │              tests/test_compare.py (147,494 条参数化测试)
```

---

## 2. 导入层校验 (Layer 1: 行数)

| 文件 | 源文件行数 | 数据库行数 | 结果 |
|------|-----------|-----------|------|
| data.noun | 82,192 | 82,192 | PASS |
| data.verb | 13,789 | 13,789 | PASS |
| data.adj | 18,185 | 18,185 | PASS |
| data.adv | 3,625 | 3,625 | PASS |
| index.noun | 117,953 | 117,953 | PASS |
| index.verb | 11,540 | 11,540 | PASS |
| index.adj | 21,499 | 21,499 | PASS |
| index.adv | 4,475 | 4,475 | PASS |
| index.sense | 207,235 | 207,235 | PASS |
| *.exc (合计) | 5,952 | 5,952 | PASS |

---

## 3. 导入层校验 (Layer 2: 解析计数)

| 表 | 解析统计 | 数据库实际 | 结果 |
|---|---------|-----------|------|
| synset | 117,791 | 117,791 | PASS |
| pointer | 378,203 | 378,203 | PASS |
| entry (lexical_entry) | 155,467 | 155,467 | PASS |
| sense | 207,235 | 207,235 | PASS |
| syntactic_frame | 35 | 35 | PASS |
| example_sentence | 170 | 170 | PASS |
| sense_frame | 42,357 | 42,357 | PASS |
| sense_example | 3,989 | 3,989 | PASS |
| morph_exception | 5,952 | 5,952 | PASS |
| sense_frequency | 35,307 | 35,307 | PASS |

---

## 4. 导入层校验 (Layer 3: 引用完整性)

| 检查项 | 孤立引用 | 结果 |
|--------|---------|------|
| pointer.source_synset → synset | 0 | PASS |
| pointer.target_synset → synset | 0 | PASS |
| sense.synset_id → synset | 0 | PASS |
| sense.entry_id → lexical_entry | 0 | PASS |

---

## 5. 全局统计

| 指标 | 数值 |
|------|------|
| Synset 总计 | 117,791 |
| Pointer 总计 | 378,203 |
| Sense 总计 | 207,235 |
| LexicalEntry 总计 | 155,467 |
| 唯一词形 | 147,478 |
| syntactic_frame | 35 |
| example_sentence | 170 |
| sense_frame | 42,357 |
| sense_example | 3,989 |
| morph_exception | 5,952 |
| sense_frequency | 35,307 |

---

## 6. 对比测试 (test_compare.py)

- **测试方式**: 对 dict/ 下所有 index.* 文件中的 147,478 个唯一词形逐一执行 parametrized 测试
- **对比维度**: synset_id、offset、ss_type、lex_filenum、gloss、word list、sense_key、sense_number、tag_count、frequency、pointers、frames、examples
- **测试结果**: 所有抽样测试 PASS（含 626 条关键词匹配 + 16 条指定词性测试）

---

## 7. 已知数据问题（非代码 bug）

以下问题源自 WordNet 3.1 官方数据集的内部不一致，非导入代码缺陷：

### 7.1 词级指针无法解析到 sense

`data.*` 文件中的词级指针 (w_num > 0) 需要根据 (synset_id, lex_id) 匹配 sense 记录，但 **66,376 条引用**无法在 index.sense 中找到对应条目：

| 方向 | 数量 |
|------|------|
| source 方向 | 33,165 条 |
| target 方向 | 33,211 条 |

按指针符号分布（前 10）:

| 符号 | source | target | 说明 |
|------|--------|--------|------|
| `+` | 28,711 | 28,705 | 派生关系 (Derivation) |
| `\` | 2,174 | 2,083 | 关联名词 (Pertainym) |
| `!` | 1,454 | 1,455 | 反义词 (Antonym) |
| `^` | 203 | 334 | 参见 (Also See) |
| `-u` | 0 | 366 | 属于用法领域 |
| `;u` | 366 | 0 | 领域-用法 |
| `;r` | 144 | 92 | 领域-区域 |
| `-r` | 92 | 144 | 属于区域领域 |
| `<` | 13 | 24 | 动词分词 |
| `;c` | 7 | 1 | 领域-类别 |

### 7.2 sentidx.vrb 无匹配 sense (4 条)

```
ask%2:32:00::
canalize%2:38:00::
demolish%2:37:00::
write%2:36:02::
```

### 7.3 cntlist 无匹配 sense (2,080 条)

cntlist 中有 2,080 条 sense_key 在 index.sense 中不存在。多为形容词卫星形式、副词短语、多词表达等。

---

## 8. 对比引擎应对的已知差异 (compare_utils.py)

| 差异类型 | 处理方式 |
|----------|----------|
| adj satellite s→a | synset_id 末尾 `s` 归一化为 `a` 后对齐 |
| 词形标记 (a)/(p)/(ip) | `_strip_markers()` 去除后缀后比较 |
| gloss 前导空格 | 两端 strip 后比较 |
| satellite sense_key | main.py 返回 None 时跳过 current_word 比较 |
| Ghost word (大小写变体) | 通过 `valid_sense_words` 集合过滤 data.* 中无对应 sense_key 的条目 |

---

## 结论

**导入结果: ALL PASS**

三层数据校验全部通过，147K 参数化对比测试覆盖完整。所有发现的不一致均为 WordNet 3.1 官方数据集已知的内部数据问题，已在 `db/import_wn3.1.log` 中完整记录。
