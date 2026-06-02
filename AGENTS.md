# AGENTS.md — wn3-1 项目指南

> 本文档面向 AI 编程助手。阅读前请假设你对本项目一无所知。

---

## 一、项目概览

**wn3-1** 是一个基于 Princeton WordNet 3.1 的纯 Python 命令行查询工具。

- **核心功能**：加载 WordNet 3.1 全部字典文件到内存，提供交互式 REPL，支持跨文件全引用追踪（index → data → sense → cntlist → frames → sents → exc）。
- **项目规模**：极小型单文件项目，仅 `main.py` 一个源码文件（约 733 行）。
- **自然语言**：代码注释、文档、交互输出均以**中文**为主。

---

## 二、技术栈与运行环境

| 项目 | 说明 |
|------|------|
| 语言 | Python 3.14+（`.python-version` 指定为 `3.14`） |
| 依赖 | **零第三方依赖**，仅使用标准库：`os`, `re`, `sys`, `dataclasses`, `pathlib`, `typing` |
| 构建工具 | `pyproject.toml` 存在但极简，无复杂构建配置 |
| 虚拟环境 | 仓库包含 `.venv/`（已加入 `.gitignore`） |
| OS 兼容 | 开发于 Windows，代码中显式处理了 Windows 的 UTF-8 编码问题 |

---

## 三、目录结构

```
wn3-1/
├── main.py                  # 唯一源码：解析器 + 查询 API + CLI
├── pyproject.toml           # 项目元数据（name=wn3-1, version=0.1.0）
├── README.md                # 当前为空
├── .python-version          # 3.14
├── .gitignore               # 忽略 __pycache__、.venv、dict/、asset/、db/
├── asset/
│   └── wn3.1.dict.tar.gz    # WordNet 3.1 原始字典压缩包（~16 MB）
├── dict/                    # **运行时必需**：存放解压后的字典文件（gitignored，目前为空）
├── db/                      # 预留目录（gitignored，目前为空）
├── tmp_inspect/             # 预留目录（gitignored，目前为空）
└── docs/
    └── WordNet3.1-Structure.md   # 极其详尽的 WordNet 3.1 数据库格式文档（中文）
```

### 关键路径约定

- **字典根目录**：`DICT_DIR = Path(__file__).parent / "dict"`
- 运行时必须在项目根目录存在 `dict/` 文件夹，且其中包含 WordNet 3.1 的标准字典文件（如 `data.noun`、`index.noun`、`index.sense`、`cntlist`、`*.exc`、`verb.Framestext` 等）。
- 这些文件通常由 `asset/wn3.1.dict.tar.gz` 解压得到。

---

## 四、如何运行

### 1. 准备字典数据

```bash
# 在项目根目录执行，将 asset 中的压缩包解压到 dict/
tar -xzf asset/wn3.1.dict.tar.gz -C .
# 注意：解压后顶层文件夹名可能不是 dict，请确保标准字典文件最终位于 dict/ 下
```

> 如果解压后产生类似 `dict/` 或 `WordNet-3.1/dict/` 的嵌套结构，请调整目录，使 `dict/data.noun` 等文件直接可被访问。

### 2. 启动交互式查询

```bash
# 使用已配置的虚拟环境
.venv\Scripts\python.exe main.py

# 或在已激活虚拟环境的情况下
python main.py
```

启动后会看到：

```
[正在加载 WordNet 3.1 数据库...]
[加载完成] 117791 synsets, 155467 index entries, 207235 senses
======================================================================
  WordNet 3.1 查询工具
  命令: <word> [n|v|a|r]    例: dog n | run v | happy a
        q / quit / exit     退出
======================================================================
```

### 3. 使用示例

```
wn> dog
wn> run v
wn> happy a
wn> q
```

---

## 五、构建与测试

### 构建

本项目**无需构建**。`pyproject.toml` 中无 `build-system` 定义，也没有打包脚本。它就是一个可直接运行的脚本。

### 测试

**当前没有任何测试文件或测试框架配置。**

- 不存在 `tests/` 目录。
- 不存在 `pytest`、`unittest` 等配置。
- 验证正确性的唯一方式是手动运行 `main.py` 并输入单词观察输出。

> 如需添加测试，建议引入 `pytest` 并在 `tests/` 目录中为 `WordNetDB` 的查询 API 编写单元测试。

---

## 六、代码架构与模块划分

所有逻辑集中在 `main.py` 中，按自上而下顺序分为五个区域：

### 1. 配置与常量区（第 16–68 行）

- `DICT_DIR`：字典根目录路径。
- `SS_TYPE_MAP` / `SS_TYPE_CODE`：词性编码映射（`n/v/a/r/s`）。
- `POINTER_DESC`：指针符号 → 人类可读语义关系名称。
- `POS_TO_NAME` / `POS_TO_FILE`：词性到文件名片段的映射（如 `a` → `adj`）。

### 2. 数据类定义区（第 71–124 行）

| 类名 | 职责 |
|------|------|
| `Pointer` | 语义关系指针（符号、目标 offset、源/目标词序号） |
| `Synset` | 同义词集（offset、词性、词列表、指针列表、gloss、frame） |
| `IndexEntry` | 索引项（lemma、词性、synset 数量、指针符号列表、offset 列表） |
| `SenseInfo` | Sense 键信息（sense_key、offset、sense_number、tag_cnt） |
| `FrameText` | 动词句法框架（编号与文本模板） |

### 3. 解析器 `WordNetDB`（第 127–493 行）

核心类，负责**一次性全量加载**所有字典文件到内存字典中：

- `_load_index(pos)` → 解析 `index.{noun|verb|adj|adv}`
- `_load_data(pos)` → 解析 `data.{noun|verb|adj|adv}`
- `_load_sense_index()` → 解析 `index.sense`
- `_load_cntlist()` → 解析 `cntlist`（语料频率）
- `_load_exc()` → 解析 `*.exc`（不规则形态）
- `_load_verb_frames()` → 解析 `verb.Framestext`
- `_load_verb_examples()` → 解析 `sents.vrb` + `sentidx.vrb`

查询 API：

- `lookup(word, pos_filter=None)`：返回该词在所有（或指定）词性中的完整信息字典列表。
- `_build_result(entry, synset)`：将一个 synset 及其关联的所有外部文件信息打包为结果字典。
- `_find_sense_key(lemma, synset)`：反向匹配 `index.sense`。
- `get_morph_exceptions(word)`：正向 + 反向查询不规则形态。

### 4. 格式化输出区（第 496–670 行）

- `print_result(result, db)`：以人类友好的中文格式打印单个 sense。
- `_print_relation_network(result, db)`：打印一跳关系网络摘要（上位、下位、部分、整体、派生、蕴含、致使等）。
- `print_morph_info(word, db)`：打印形态学例外信息。

### 5. 交互入口区（第 672–733 行）

- `interactive(db)`：REPL 循环，解析用户输入，调用 `lookup` 并渲染结果。
- `main()`：强制 UTF-8（解决 Windows GBK 问题），实例化 `WordNetDB`，进入交互循环。

---

## 七、代码风格指南

### 语言与注释

- **注释和文档字符串使用中文**。新增功能或修改时请保持中文注释风格。
- 交互输出（`print`）也使用中文，并大量使用全角符号（如 `【】`、`▲`、`▼`）。

### 命名规范

- 类名：`PascalCase`（如 `WordNetDB`, `IndexEntry`）。
- 函数/变量：`snake_case`。
- 私有方法：以单下划线开头（如 `_load_data`, `_build_result`）。
- 常量：全大写（如 `POINTER_DESC`, `POS_FILES`）。

### 编码约定

- 文件头使用 `from __future__ import annotations`。
- 使用 `dataclass` 定义领域模型。
- 类型注解已广泛使用，新增代码应继续标注类型。
- 字符串拼接优先使用 f-string。
- 文件读取统一使用 `encoding="utf-8"`。

### 重要实现细节（修改前必读）

1. **offset 不是全局唯一主键**：必须组合 `offset + pos`（如 `00001740n`）才能唯一标识一个 synset。不同 `data.*` 文件中可能出现相同 offset。
2. **Sense 是关联枢纽**：查询几乎都要经过 `Sense` → `Synset` → `LexicalEntry` 的链路。
3. **指针的自反性**：`Pointer` 连接的是同一实体（`Synset`）的两个实例，需要两个外键都指向 `Synset`。
4. **形容词卫星（`s`）的特殊性**：`ss_type` 为 `s` 的形容词卫星通过 `&` 指针依赖核心形容词（`a`）。其 `sense_key` 包含 `head_word:head_id`。
5. **动词 frames 解析较为特殊**：当前使用正则表达式 `re.findall(r'\+\s*(\d+)\s+(\d+)', pre_gloss)` 从原始行中提取，而非基于已 split 的 `parts` 数组。修改时需特别小心。

---

## 八、数据文件与外部依赖

### 数据来源

- 压缩包：`asset/wn3.1.dict.tar.gz`
- 原始来源：Princeton University WordNet 3.1（`https://wordnet.princeton.edu/`）

### 运行时必需文件清单

以下文件必须存在于 `dict/` 目录中，否则对应功能会跳过或报错：

| 文件 | 功能 | 是否必需 |
|------|------|:--------:|
| `data.noun`, `data.verb`, `data.adj`, `data.adv` | Synset 定义与关系 | ✅ |
| `index.noun`, `index.verb`, `index.adj`, `index.adv` | 词形索引 | ✅ |
| `index.sense` | Sense Key 映射 | ⚠️ 缺失则 sense_key 为 None |
| `cntlist` | 语料频率统计 | ⚠️ 缺失则无频率信息 |
| `noun.exc`, `verb.exc`, `adj.exc`, `adv.exc` | 不规则形态 | ⚠️ 缺失则无法处理例外变形 |
| `verb.Framestext` | 动词句法框架模板 | ⚠️ 缺失则无框架输出 |
| `sentidx.vrb`, `sents.vrb` | 动词例句 | ⚠️ 缺失则无例句输出 |

---

## 九、安全注意事项

- **无网络通信**：本项目是纯离线工具，不发起任何网络请求。
- **仅本地文件读取**：`WordNetDB` 只读取 `dict/` 下的文本字典文件。
- **无用户输入执行**：REPL 接收的单词仅用于字典查询，不存在 `eval` 或代码注入风险。
- **无敏感信息**：字典文件为公开学术数据集，代码中不包含密钥、Token 或凭证。

---

## 十、常见任务速查

| 任务 | 命令/操作 |
|------|-----------|
| 运行程序 | `python main.py` |
| 解压字典数据 | `tar -xzf asset/wn3.1.dict.tar.gz` 并确保文件位于 `dict/` 下 |
| 查询单词 | 在 REPL 中输入 `<word> [n\|v\|a\|r]` |
| 退出 REPL | 输入 `q`、`quit` 或 `exit` |
| 添加测试 | 建议新建 `tests/` 目录并引入 `pytest` |

---

*最后更新：2026-06-02*
