# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the interactive WordNet query tool (file-based, requires dict/ populated)
uv run python main.py

# Import WordNet data into SQLite (requires asset/wn3.1.dict.tar.gz)
uv run python import_wn.py

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_compare.py

# Run tests matching a keyword
uv run pytest -k "dog"

# Run all tests, stop on first failure, with verbose output
uv run pytest -x -v --tb=long
```

## Architecture

This project has three layers:

1. **Source data** — `asset/wn3.1.dict.tar.gz` (Princeton WordNet 3.1), extracted to `dict/`
2. **File-based query** — `main.py` loads all `dict/*` files into in-memory Python dataclasses (`WordNetDB`). APIs: `lookup(word, pos_filter)`, `get_morph_exceptions(word)`
3. **SQLite import + comparison test** — `import_wn.py` parses the same source files into `db/wn.db` (11 tables). `tests/` verifies that file-based and DB-based queries return identical results

**Key classes:**
- `main.py::WordNetDB` — in-memory backend backed by `dict/` text files; used as the "ground truth" reference
- `db_backend.py::DbWordNetDB` — SQLite backend mirroring the same `lookup()` API; loads all data into memory on init
- `compare_utils.py::compare_lookup_results()` — deep comparison bridging known differences between the two backends

**Key files:**
| File | Purpose |
|------|---------|
| `main.py` | File-based WordNet query tool + interactive REPL |
| `import_wn.py` | One-shot pipeline: extract tar.gz → parse → insert into SQLite |
| `tests/conftest.py` | Session-scoped fixtures `file_db` and `db_db` |
| `tests/db_backend.py` | SQLite `lookup()` backend matching main.py output structure |
| `tests/compare_utils.py` | Diff engine normalizing s→a, marker suffixes, gloss whitespace |
| `tests/test_compare.py` | 147K parametrized tests — every lemma across both backends |

**Data flow for comparison tests:**
```
asset/wn3.1.dict.tar.gz
    ├─[tar extract]→ dict/  ──[main.py WordNetDB]──→ file_db fixture
    └─[import_wn.py]──→ db/wn.db  ──[DbWordNetDB]──→ db_db fixture
                                  ↓
                         compare_lookup_results()
```

## Known data issues (not bugs)

These are inherent to WordNet 3.1's internal inconsistencies, documented in `import_wn3.1.log`:

- **Adj satellite s→a normalization**: `main.py` treats all `data.adj` synsets as pos `a` (ignoring `ss_type=s`), so the DB pos `s` must be normalized to `a` during comparison. `import_wn.py` corrects satellite pointer targets via a SQL UPDATE.
- **66,376 word-level pointers** cannot resolve `(synset_id, lex_id)` to a sense row — gap between `data.*` and `index.sense`. Distributed across `+` (derivation), `\` (pertainym), `!` (antonym), `^` (also see), domain pointers
- **4 sentidx.vrb** sense keys and **2,080 cntlist** sense keys don't exist in `index.sense`
- **Ghost words**: `data.*` contains case variants (e.g. `Earth(0)` vs `earth(2)`) where only one is in `index.sense`. `compare_utils` filters these using a `valid_sense_words` set
- **Word marker suffixes** `(a)`, `(p)`, `(ip)` in data.* words must be stripped for comparison; `compare_utils._norm_word()` handles this

## Key constraints

- Python 3.14+ required (`.python-version`)
- Package manager: `uv`
- Zero third-party dependencies (stdlib only for `main.py`; `import_wn.py` too)
- `db/wn.db` is ~92MB, gitignored
- All comments and UI output are in Chinese; code identifiers in English
- Always use `uv run` prefix for Python commands
