# WordNet 3.1 数据库文件结构详解

> 数据来源：Princeton University WordNet 3.1 (`https://wordnet.princeton.edu/download/current-version#win`)  
> 本文基于 `dict/` 目录下的原始数据库文件进行分析。

---

## 一、整体架构

WordNet 3.1 数据库采用**纯文本文件**存储，按词性（POS: Part of Speech）分文件组织。核心设计理念是 **Synset（同义词集）**：每个 synset 由一组语义等价或近义的词组成，并带有唯一的偏移量（offset）作为全局 ID。

### 1.1 文件分类总览

```
dict/
├── 核心数据文件（运行时必需）
│   ├── data.noun      # 名词 synset 定义与关系
│   ├── data.verb      # 动词 synset 定义与关系
│   ├── data.adj       # 形容词 synset 定义与关系
│   ├── data.adv       # 副词 synset 定义与关系
│   ├── index.noun     # 名词词形 → synset 索引
│   ├── index.verb     # 动词词形 → synset 索引
│   ├── index.adj      # 形容词词形 → synset 索引
│   ├── index.adv      # 副词词形 → synset 索引
│   ├── index.sense    # Sense Key → synset 映射（语料标注用）
│   ├── cntlist        # 各 sense 的语料频率统计
│   ├── cntlist.rev    # 频率统计（反向格式）
│   ├── noun.exc       # 不规则名词形态
│   ├── verb.exc       # 不规则动词形态
│   ├── adj.exc        # 不规则形容词形态
│   ├── adv.exc        # 不规则副词形态
│   └── cousin.exc     # （空文件，预留）
│
├── 动词句法框架文件
│   ├── verb.Framestext    # 35 种标准句法框架模板
│   ├── sentidx.vrb        # 动词 sense → 例句模板编号
│   └── sents.vrb          # 例句文本库
│
└── 构建源文件（仅重新构建时需要）
    └── dbfiles/         # grind 编译器的原始输入
        ├── noun.Tops    # 顶层概念（entity）
        ├── noun.act ~ noun.time   # 按主题细分的名词源文件
        ├── adj.all / adj.pert / adj.ppl
        ├── adv.all
        ├── verb.body ~ verb.weather
        └── cntlist
```

### 1.2 构建流程

```
  dbfiles/ (词法编纂源文件)
      │
      ▼
 [ grind 工具编译 ]  ←── log.grind.3.1 (构建日志)
      │
      ├──► data.*    ──┐
      ├──► index.*   ──┼──► 应用程序/库直接读取
      ├──► index.sense─┘
      ├──► *.exc / cntlist / verb.Framestext / ...
```

---

## 二、关系数据库概念模型（ER 图）

将 WordNet 3.1 的文本文件映射为关系数据库时，可抽象出以下实体与关系。下图采用 **Mermaid ER Diagram** 语法描述，可在支持 Mermaid 的 Markdown 阅读器中直接渲染。

### 2.1 ER 图（Mermaid）

```mermaid
erDiagram
    SYNSET ||--o{ SENSE : "包含 (contains)"
    LEXICAL_ENTRY ||--o{ SENSE : "拥有 (has)"
    SYNSET ||--o{ POINTER : "关系起点 (source)"
    SYNSET ||--o{ POINTER : "关系终点 (target)"
    SENSE ||--o{ POINTER : "词级起点 (optional)"
    SENSE ||--o{ POINTER : "词级终点 (optional)"
    SENSE ||--o{ SENSE_FRAME : "使用框架"
    SYNTACTIC_FRAME ||--o{ SENSE_FRAME : "被使用"
    SENSE ||--o{ SENSE_EXAMPLE : "拥有例句"
    EXAMPLE_SENTENCE ||--o{ SENSE_EXAMPLE : "用于"
    LEXICAL_ENTRY ||--o{ MORPH_EXCEPTION : "例外形态"
    SENSE ||--o{ SENSE_FREQUENCY : "频率统计"

    SYNSET {
        string synset_id PK "offset+pos 复合主键, 如 00001740n"
        string offset UK "8位文件偏移量"
        string pos "词性: n/v/a/r/s"
        int lex_filenum "词法编纂文件编号 00~44"
        string ss_type "a/core, s/satellite, r/adv, v/verb, n/noun"
        string gloss "定义与例句"
        int word_count "同义词数量"
    }

    LEXICAL_ENTRY {
        int entry_id PK "代理主键"
        string lemma UK,FK "词形, 空格转下划线"
        string pos "词性"
        int synset_count "sense总数"
        int tagged_sense_count "被标注的sense数"
        int pointer_type_count "参与的关系类型数"
    }

    SENSE {
        int sense_id PK "代理主键"
        int entry_id FK "→ LexicalEntry"
        string synset_id FK "→ Synset"
        string sense_key UK "如 breathe%2:29:00::"
        int sense_number "该lemma下的sense序号"
        int tag_cnt "语料标注次数"
        int lex_id "该词在lex文件中的局部ID"
    }

    POINTER {
        int pointer_id PK "代理主键"
        string pointer_symbol "如 @ ~ ! + = 等"
        string source_synset_id FK "→ Synset"
        string target_synset_id FK "→ Synset"
        int source_sense_id FK "→ Sense, word-level时为NULL"
        int target_sense_id FK "→ Sense, word-level时为NULL"
    }

    SYNTACTIC_FRAME {
        int frame_id PK "代理主键"
        int frame_number "1~35"
        string frame_text "如 'Somebody ----s something'"
    }

    SENSE_FRAME {
        int sense_id PK,FK "→ Sense"
        int frame_id PK,FK "→ SyntacticFrame"
    }

    EXAMPLE_SENTENCE {
        int sentence_id PK "代理主键"
        int sentence_number "原始编号"
        string sentence_text "例句, %s为占位符"
    }

    SENSE_EXAMPLE {
        int sense_id PK,FK "→ Sense"
        int sentence_id PK,FK "→ ExampleSentence"
    }

    MORPH_EXCEPTION {
        int exception_id PK "代理主键"
        string pos "n/v/a/r"
        string surface_form "变形后形式"
        string base_form "原形"
    }

    SENSE_FREQUENCY {
        int freq_id PK "代理主键"
        int sense_id FK "→ Sense"
        int count "语料出现次数"
        int rank "频率排名"
    }
```

### 2.2 实体说明

| 实体 | 对应文件 | 说明 |
|------|----------|------|
| **Synset** | `data.*` | 同义词集是 WordNet 的核心。主键建议用 `offset` + `pos` 的复合键，因为不同 `data.*` 文件中可能出现相同的 offset 值（虽然 Princeton 的 grind 工具通常保证全局唯一，但按词性隔离更安全）。 |
| **LexicalEntry** | `index.*` | 一个 lemma + pos 的组合。同一个词形在不同词性中视为不同词条（如 `run` 在名词和动词中各有一条记录）。 |
| **Sense** | `index.sense` + `data.*` 中的词列表 | 连接 LexicalEntry 与 Synset 的**关联实体**。同一个 lemma 在不同 synset 中出现时，每条都是一个独立的 Sense。`sense_key` 是全局唯一标识符。 |
| **Pointer** | `data.*` 中的指针字段 | 描述 Synset 之间（或 Sense 之间）的语义关系。当 `source_sense_id` / `target_sense_id` 为 NULL 时，表示 **Synset 级关系**（如 `dog @ animal`）；非 NULL 时表示 **Word 级关系**（如 `breathe + breath` 中派生词可能精确到具体词形）。 |
| **SyntacticFrame** | `verb.Framestext` | 动词的 35 种标准句法框架模板。 |
| **SenseFrame** | `data.verb` 末尾的 frame 编码 | 多对多关联：某个动词的特定 sense 可以使用多种句法框架。 |
| **ExampleSentence** | `sents.vrb` | 动词例句文本库。 |
| **SenseExample** | `sentidx.vrb` | 多对多关联：某个 sense 可以对应多条例句编号。 |
| **MorphException** | `*.exc` | 不规则形态变化表。 |
| **SenseFrequency** | `cntlist` | 各 sense 在 SemCor 等语料中的频率统计。 |

### 2.3 关系基数（Cardinality）详解

| 关系 | 基数 | 说明 |
|------|:----:|------|
| `Synset` ── `Sense` | **1 : N** | 一个 synset 包含多个词形（如 `{breathe, respire, take_a_breath, suspire}`），每个词形在该 synset 中对应一条 Sense 记录。 |
| `LexicalEntry` ── `Sense` | **1 : N** | 一个词项（如动词 `breathe`）在字典中只有 1 个 sense，对应 1 条 Sense 记录；而 `abandon` 有 5 个 senses，对应 5 条记录。 |
| `Synset` ── `Pointer` (source) | **1 : N** | 一个 synset 可以是多条关系的起点（如 `entity` 有 3 条 hyponym 指针）。 |
| `Synset` ── `Pointer` (target) | **1 : N** | 一个 synset 也可以是多条关系的终点（如 `animal` 被多个下位词指向）。 |
| `Sense` ── `Pointer` (word-level) | **0..1 : 0..N** | 大多数指针是 synset 级的，不涉及具体 sense；少数 word-level 指针（如 `+` 派生关系）会精确到 synset 中的第几个词。 |
| `Sense` ── `SyntacticFrame` | **N : M** | 通过 `SenseFrame` 关联表实现多对多。如 `breathe` 既可用 "Somebody ----s" 框架，也可用 "Somebody ----s something" 框架。 |
| `Sense` ── `ExampleSentence` | **N : M** | 通过 `SenseExample` 关联表实现多对多。 |
| `LexicalEntry` ── `MorphException` | **1 : N** | 一个词项可有多条不规则变形（如 `go` → `went`, `gone`）。 |

### 2.4 建模要点与陷阱

1. **offset 不能单独做主键**  
   虽然 grind 工具生成的 offset 在全部 `data.*` 文件间通常是全局唯一的，但按 WordNet 设计规范，offset 本质是**文件内的字节偏移量**。因此最严谨的做法是使用 **`offset + pos`** 作为复合主键，或引入代理主键。

2. **Sense 是核心关联枢纽**  
   几乎所有查询都要通过 `Sense` 表：
   - 查一个词的所有释义 → `LexicalEntry` → `Sense` → `Synset`
   - 查一个 synset 的所有同义词 → `Synset` → `Sense` → `LexicalEntry`
   - 查词频 → `SenseFrequency` → `Sense`
   - 查例句/框架 → `Sense` → `SenseExample` / `SenseFrame`

3. **Pointer 的自反性**  
   `Pointer` 表是一个**自反关系表**（连接同一实体 `Synset` 的两个实例）。在 SQL 中需要两个外键都指向 `Synset` 表。同时支持 word-level 精确关联时，需要额外引入对 `Sense` 表的引用。

4. **形容词卫星的特殊性**  
   形容词卫星（ss_type=`s`）在 `data.adj` 中存储，但它通过 `&` 指针依赖一个核心形容词（ss_type=`a`）。在 Sense 表中，卫星形容词的 `sense_key` 包含 `head_word:head_id`（如 `0%5:00:00:cardinal:00`），这可以作为外键指向核心形容词的 Sense 记录。

5. **Domain 关系的双向性**  
   `;c`（domain category）和 `-c`（domain member category）是**同一对关系**的两个方向。在关系模型中，两者都存储为 `Pointer` 记录，仅 `pointer_symbol` 不同。查询时可以通过反向查找实现双向导航。

---

## 三、核心文件格式详解

### 2.1 `data.*` — Synset 定义文件

每个词性一个文件。每行代表一个 **synset**（同义词集）。前 29 行为许可证声明，从第 30 行开始为数据。

#### 格式语法

```
<offset> <lex_filenum> <ss_type> <w_cnt> <word> <lex_id>... <p_cnt> [<ptr> <pos> <target_offset> <target_pos> <source/target>]... | <gloss>
```

| 字段 | 说明 | 示例 |
|------|------|------|
| `offset` | 该 synset 在文件中的字节偏移量，**8 位数字，作为全局唯一 ID** | `00001740` |
| `lex_filenum` | 词法编纂文件编号（语义类别） | `03` = noun.Tops, `29` = verb.body |
| `ss_type` | 同义词集类型 | `n`=名词, `v`=动词, `a`=形容词, `r`=副词, `s`=形容词卫星 |
| `w_cnt` | 该 synset 中包含的词形数量（16 进制） | `01`~`19` |
| `word lex_id` | 词形 + 词在该文件中的局部 ID | `entity 0` |
| `p_cnt` | 指针（关系）数量 | `003` |
| `ptr pos target_offset ...` | 关系类型 + 目标词性 + 目标偏移量 + 源/目标词序号 | `~ 00001930 n 0000` |
| `\| gloss` | 定义（gloss），可包含例句 | `that which is perceived...` |

#### 名词示例：`entity` (offset `00001740`)

```
00001740 03 n 01 entity 0 003 ~ 00001930 n 0000 ~ 00002137 n 0000 ~ 04431553 n 0000 | that which is perceived or known or inferred to have its own distinct existence (living or nonliving)
```

拆解：
- `00001740`：offset ID
- `03`：lexicographer file = noun.Tops
- `n`：名词
- `01 entity 0`：包含 1 个词形 "entity"
- `003`：3 个指针
- `~ 00001930 n 0000`：下位词 → `physical_entity`
- `~ 00002137 n 0000`：下位词 → `abstraction`
- `~ 04431553 n 0000`：下位词 → `thing`
- `|` 后：定义文本

#### 动词示例：`breathe` (offset `00001740`)

```
00001740 29 v 04 breathe 0 take_a_breath 0 respire 0 suspire 3 021 * 00005041 v 0000 * 00004227 v 0000 + 03121972 a 0301 + 00832852 n 0303 ... 02 + 02 00 + 08 00 | draw air into, and expel out of, the lungs; "I can breathe better when the air is clean"; "The patient is respiring"
```

拆解：
- `00001740`：offset ID
- `29`：lexicographer file = verb.body
- `v`：动词
- `04 breathe 0 take_a_breath 0 respire 0 suspire 3`：4 个同义词，其中 suspire 的 lex_id=3
- `021`：21 个指针
- `* 00005041 v 0000`：蕴含(entailment) → `inhale`
- `* 00004227 v 0000`：蕴含(entailment) → `exhale`
- `+ 03121972 a 0301`：派生关系 → 形容词 `respiratory`
- `+ 00832852 n 0303`：派生关系 → 名词 `breath`
- `02 + 02 00 + 08 00`：句法框架编号（对应 verb.Framestext 中的模板）

#### 形容词示例：`able` (offset `00001740`)

```
00001740 00 a 01 able 0 005 = 05207437 n 0000 = 05624029 n 0000 + 05624029 n 0101 + 05207437 n 0101 ! 00002098 a 0101 | (usually followed by `to') having the necessary means...
```

拆解：
- `00`：lexicographer file = adj.all
- `a`：核心形容词（head synset）
- `! 00002098 a 0101`：反义词 → `unable`
- `= 05207437 n 0000`：属性关系 → 名词 `ability`
- `+ 05624029 n 0101`：派生关系 → 名词 `ability`

#### 副词示例：`a_cappella` (offset `00001740`)

```
00001740 02 r 02 a_cappella 0 a_capella 0 002 \ 02260096 a 0202 \ 02260096 a 0101 | without musical accompaniment; "they performed a cappella"
```

拆解：
- `r`：副词
- `\ 02260096 a 0202`：pertainym（派生自形容词）→ `a_cappella` (adj)

---

### 2.2 `index.*` — 词形索引文件

用于从 **lemma（词形）** 快速定位到所有相关的 synset offset。

#### 格式语法

```
<lemma> <pos> <synset_cnt> <p_cnt> [<ptr_symbol>...] <sense_cnt> <tagsense_cnt> [<offset>...]
```

| 字段 | 说明 |
|------|------|
| `lemma` | 词形（小写，空格用下划线代替） |
| `pos` | 词性（n/v/a/r） |
| `synset_cnt` | 该词在字典中不同 synset 的数量（即 sense 数量） |
| `p_cnt` | 该词参与的关系类型数量 |
| `ptr_symbol...` | 该词在 data 文件中出现的所有指针类型符号列表 |
| `sense_cnt` | 同 synset_cnt |
| `tagsense_cnt` | 在 SemCor 语料中被标注过的 sense 数量 |
| `offset...` | 该词所属每个 synset 在 data 文件中的偏移量列表 |

#### 示例：`index.verb` 中的 `abandon`

```
abandon v 5 4 @ ~ $ + 5 5 02232813 02232523 02080923 00614907 00615748
```

拆解：
- `abandon`：词形
- `v`：动词
- `5`：5 个 sense（在 5 个不同 synset 中出现）
- `4`：涉及 4 种指针类型
- `@ ~ $ +`：出现过的指针类型 = hypernym, hyponym, verb_group, derivation
- `5 5`：5 个 senses，5 个被标注过
- `02232813 ...`：5 个 synset 的 offset

---

### 2.3 `index.sense` — Sense 索引

连接 **Sense Key** 与 **synset offset** 的核心映射文件，主要用于语料标注（如 SemCor）和词义消歧。

#### 格式语法

```
<sense_key> <offset> <sense_number> <tag_cnt>
```

| 字段 | 说明 |
|------|------|
| `sense_key` | `lemma%ss_type:lex_filenum:lex_id[:head_word:head_id]` |
| `offset` | 对应 synset 在 data 文件中的偏移量 |
| `sense_number` | 该 sense 在该 lemma 所有 senses 中的序号（从 1 开始） |
| `tag_cnt` | 在语料中的出现次数（0 = 未标注） |

#### Sense Key 编码规则

```
lemma%ss_type:lex_filenum:lex_id:head_word:head_id
```

- `ss_type`：词性数字编码  
  `1`=noun, `2`=verb, `3`=adj, `4`=adv, `5`=adj satellite
- `lex_filenum`：词法编纂文件编号
- `lex_id`：该词在该文件中的局部序号（00~99）
- `head_word:head_id`：**仅形容词卫星**需要，指向其核心形容词（head synset）

#### 示例

```
'hood%1:15:00:: 08659519 1 0
```
- `'hood`：词形
- `%1:15:00::`：名词(1)，lex file 15 (noun.location)，lex_id=00
- `08659519`：对应 synset offset
- `1`：该词的第 1 个 sense
- `0`：未在语料中标注

```
0%5:00:00:cardinal:00 02193771 1 3
```
- `0`：词形
- `%5:00:00:cardinal:00`：**形容词卫星**(5)，head_word=`cardinal`，head_id=00
- `02193771`：对应 synset offset
- `1`：第 1 个 sense
- `3`：在语料中出现 3 次

---

## 四、实体间关系（指针类型）完整明细

WordNet 中 synset 之间的关系通过 **指针（pointer）** 表示。下表列出所有指针符号及其语义。

### 3.1 通用关系（名词/动词/形容词/副词共有）

| 符号 | 名称 | 适用词性 | 方向 | 说明 | 示例 |
|:----:|------|:--------:|:----:|------|------|
| `!` | **ANTONYM** | adj, adv | ↔ | 反义词 | `able ! unable` |
| `@` | **HYPERNYM** | noun, verb | ↑ | 上位词（is-a 关系） | `dog @ animal` |
| `@i` | **INSTANCE HYPERNYM** | noun | ↑ | 实例上位词 | `Einstein @i physicist` |
| `~` | **HYPONYM** | noun, verb | ↓ | 下位词 | `animal ~ dog` |
| `~i` | **INSTANCE HYPONYM** | noun | ↓ | 实例下位词 | `physicist ~i Einstein` |
| `#m` | **MEMBER MERONYM** | noun | ← | 成员部分 | `flock #m bird` |
| `#s` | **SUBSTANCE MERONYM** | noun | ← | 物质部分 | `steel #s iron` |
| `#p` | **PART MERONYM** | noun | ← | 部件部分 | `car #p engine` |
| `%m` | **MEMBER HOLONYM** | noun | → | 成员整体 | `bird %m flock` |
| `%s` | **SUBSTANCE HOLONYM** | noun | → | 物质整体 | `iron %s steel` |
| `%p` | **PART HOLONYM** | noun | → | 部件整体 | `engine %p car` |
| `=` | **ATTRIBUTE** | adj, noun | ↔ | 属性（adj↔noun） | `beautiful = beauty` |
| `+` | **DERIVATION** | noun, verb, adj, adv | ↔ | 派生关系（跨词性） | `breathe + breath` |
| `;c` | **DOMAIN CATEGORY** | n,v,adj,adv | → | 领域-类别 | `cell ;c biology` |
| `;r` | **DOMAIN REGION** | n,v,adj,adv | → | 领域-区域 | `tokyo ;r japan` |
| `;u` | **DOMAIN USAGE** | n,v,adj,adv | → | 领域-用法 | `aint ;u slang` |
| `-c` | **DOMAIN MEMBER CAT** | n,v,adj,adv | ← | 属于某类别领域 | `biology -c cell` |
| `-r` | **DOMAIN MEMBER REG** | n,v,adj,adv | ← | 属于某区域领域 | `japan -r tokyo` |
| `-u` | **DOMAIN MEMBER USG** | n,v,adj,adv | ← | 属于某用法领域 | `slang -u aint` |
| `^` | **ALSO SEE** | verb, adj | ↔ | 参见（语义关联） | `kill ^ slay` |

### 3.2 形容词特有关系

| 符号 | 名称 | 说明 | 示例 |
|:----:|------|------|------|
| `&` | **SIMILAR TO** | 形容词卫星 ↔ 核心形容词 | `nascent & emergent` |
| `\` | **PERTAINYM** | 派生/关联名词（adj↔noun） | `monthly \ month` |
| `<` | **PARTICIPLE OF VERB** | 分词 ↔ 动词 | `running < run` |

> 注：形容词卫星（ss_type=`s`）通过 `&` 指向核心形容词（ss_type=`a`），核心形容词没有 `&` 指针。

### 3.3 动词特有关系

| 符号 | 名称 | 说明 | 示例 |
|:----:|------|------|------|
| `*` | **ENTAILMENT** | 蕴含（做A必然做B） | `sneeze * exhale` |
| `>` | **CAUSE** | 致使（做A导致B发生） | `kill > die` |
| `$` | **VERB GROUP** | 同一语义组的动词 | `breathe $ respire` |

### 3.4 关系方向速查

```
上位/下位：      @ (hypernym)  ←──→  ~ (hyponym)
实例关系：       @i            ←──→  ~i
整体/部分：      #m/#s/#p      ←──→  %m/%s/%p
领域：           ;c/;r/;u      ←──→  -c/-r/-u
反义：           !             ←──→  !
属性：           =             ←──→  =
派生：           +             ←──→  +
蕴含：           *             ────→  (单向)
致使：           >             ────→  (单向)
动词组：         $             ←──→  $
参见：           ^             ←──→  ^
相似：           &             ←──→  (卫星→核心)
```

---

## 五、辅助文件详解

### 4.1 `*.exc` — 形态学例外文件

用于处理**不规则**的词形变化，格式为 `变形形式 原形`。

**`noun.exc`**（不规则复数）：
```
aardwolves aardwolf
abaci abacus
addenda addendum
```

**`verb.exc`**（不规则时态/分词）：
```
abetted abet
abode abide
accompanied accompany
```

**`adj.exc`**（不规则比较级/最高级）：
```
angrier angry
angriest angry
airier airy
```

**`adv.exc`**（不规则副词比较级）：
```
best well
better well
farther far
```

### 4.2 `cntlist` / `cntlist.rev` — 词频统计

按语料出现频率降序排列：

```
10742 be%2:42:03:: 1
 6833 person%1:03:00:: 1
 3019 be%2:42:06:: 2
```

格式：`count sense_key rank`

### 4.3 动词句法框架

**`verb.Framestext`** — 35 种标准句法模板：
```
1	1  Something ----s
2	2  Somebody ----s
8	8  Somebody ----s something
```

**`sentidx.vrb`** — 动词 sense → 例句模板映射：
```
abash%2:37:00:: 126,127
```

**`sents.vrb`** — 例句文本（`%s` 为动词占位符）：
```
1 The children %s to the playground
10 The cars %s down the avenue
```

---

## 六、完整查询示例

以动词 **"breathe"** 为例，展示如何跨文件追踪完整信息。

### Step 1：从 `index.verb` 找到 offsets

```
breathe v 1 4 * $ @ ~ + 1 1 00001740
```
- `breathe` 在字典中只有 **1 个 sense**
- 对应的 synset offset 为 `00001740`

### Step 2：从 `data.verb` 读取完整 synset

```
00001740 29 v 04 breathe 0 take_a_breath 0 respire 0 suspire 3 021 \
  * 00005041 v 0000        ← entailment: inhale
  * 00004227 v 0000        ← entailment: exhale
  + 03121972 a 0301        ← derivation: respiratory (adj)
  + 00832852 n 0303        ← derivation: breath (noun)
  + 04087945 n 0301        ← derivation: breath (noun, another)
  ...
  02 + 02 00 + 08 00       ← syntax frames
  | draw air into, and expel out of, the lungs; \
    "I can breathe better when the air is clean"; \
    "The patient is respiring"
```

**同义词**：breathe, take_a_breath, respire, suspire  
**上位词**：无（顶级概念，verb.body 类别）  
**蕴含**：inhale（吸气）, exhale（呼气）  
**派生**：respiratory (adj), breath (noun)  
**句法**：框架 02, 08

### Step 3：从 `verb.Framestext` 解析句法

```
2  Somebody ----s
8  Somebody ----s something
```
对应例句："The patient **breathes**" / "The patient **breathes** air"

### Step 4：从 `index.sense` 确认 sense key

```
breathe%2:29:00:: 00001740 1 0
```
- ss_type=2 (verb), lex file=29 (verb.body), lex_id=00
- offset=`00001740`，sense number=1，未标注

### Step 5：追踪到上位网络（示例）

```
breathe (00001740)
    ↓ (no hypernym, top of verb.body)
```

对比名词 **"entity"** 的层级：

```
entity (00001740)
    ├─→ physical_entity (00001930)
    │       ├─→ object (00002684)
    │       │       ├─→ whole (00003553)
    │       │       │       └─→ living_thing (00004258)
    │       │       │               └─→ organism (00004475)
    │       │       │                       └─→ animal (00015568)
    │       │       │                               └─→ dog (...)
    │       └─→ causal_agent (00007347)
    │               └─→ person (00007846)
    └─→ abstraction (00002137)
```

---

## 七、统计数据

根据 `log.grind.3.1`，WordNet 3.1 的整体规模：

| 指标 | 数量 |
|------|------|
| 名词 synset | 82,192 |
| 动词 synset | 13,789 |
| 核心形容词 synset | 3,807 |
| 副词 synset | 3,625 |
| Pertainym synset | 3,661 |
| 形容词卫星 synset | 10,717 |
| **Synset 总计** | **117,791** |
| 指针（关系）总计 | 225,204 |
| 同义词（词形出现）总计 | 207,272 |
| 唯一词形 | 147,478 |
| 长度 1 的词形 | 83,253 |
| 长度 2 的词形 | 54,562 |
| 定义（gloss）总计 | 117,791 |

---

## 八、附录：Lexicographer File 编号对照表

| 编号 | 文件名 | 语义类别 |
|:----:|--------|----------|
| 00 | adj.all | 泛形容词 |
| 01 | adj.pert | Pertainym 形容词 |
| 02 | adv.all | 泛副词 |
| 03 | noun.Tops | 顶层抽象概念 |
| 04 | noun.act | 行为/活动 |
| 05 | noun.animal | 动物 |
| 06 | noun.artifact | 人工制品 |
| 07 | noun.attribute | 属性 |
| 08 | noun.body | 身体部位 |
| 09 | noun.cognition | 认知/思维 |
| 10 | noun.communication | 交流 |
| 11 | noun.event | 事件 |
| 12 | noun.feeling | 情感 |
| 13 | noun.food | 食物 |
| 14 | noun.group | 群体 |
| 15 | noun.location | 地点 |
| 16 | noun.motive | 动机 |
| 17 | noun.object | 物体 |
| 18 | noun.person | 人物 |
| 19 | noun.phenomenon | 现象 |
| 20 | noun.plant | 植物 |
| 21 | noun.possession | 财产 |
| 22 | noun.process | 过程 |
| 23 | noun.quantity | 数量 |
| 24 | noun.relation | 关系 |
| 25 | noun.shape | 形状 |
| 26 | noun.state | 状态 |
| 27 | noun.substance | 物质 |
| 28 | noun.time | 时间 |
| 29 | verb.body | 身体动作 |
| 30 | verb.change | 变化 |
| 31 | verb.cognition | 认知动作 |
| 32 | verb.communication | 交流动作 |
| 33 | verb.competition | 竞争动作 |
| 34 | verb.consumption | 消费动作 |
| 35 | verb.contact | 接触动作 |
| 36 | verb.creation | 创造动作 |
| 37 | verb.emotion | 情感动作 |
| 38 | verb.motion | 运动 |
| 39 | verb.perception | 感知 |
| 40 | verb.possession | 拥有 |
| 41 | verb.social | 社交 |
| 42 | verb.stative | 状态动词 |
| 43 | verb.weather | 天气 |
| 44 | adj.ppl | 过去分词形容词 |
