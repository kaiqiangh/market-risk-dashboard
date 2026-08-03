#!/usr/bin/env bash
# ============================================================
# scan-cn.sh — scan the repo for residual Chinese characters.
#
# Full-repo scan by default (git ls-files, excluding lockfiles /
# node_modules / dist / .workbuddy). Pass explicit paths to scan
# only those (e.g. scripts/scan-cn.sh src/ config/).
#
# Compliance whitelist: data values / product copy that are
# intentionally bilingual or consumed as data (zh-CN locales,
# fixtures, public data, README.zh-CN.md, glossary.md, format.ts
# bilingual maps, universe.ts company names, YAML label/note/
# name_zh/disclaimer/keywords values, build_prompt zh-CN template,
# akshare Chinese column names, tests i18n value assertions,
# index.html bilingual browser shell). These are reported as
# "compliant" and do not fail the scan.
#
# Exit code: 0 when there are no violations, 1 otherwise.
#
# Usage: scripts/scan-cn.sh [--verbose] [paths...]
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERBOSE=0
if [[ "${1:-}" == "--verbose" ]]; then
  VERBOSE=1
  shift
fi

python3 - "$VERBOSE" "$@" <<'PYEOF'
import os
import re
import subprocess
import sys

verbose = bool(int(sys.argv[1]))
targets = sys.argv[2:]

CJK = re.compile(r"[\u4e00-\u9fff]")

# ---------------------------------------------------------------
# Compliance whitelist. Each rule is (path_prefix, line_matcher or None).
# path_prefix: file path prefix that the rule applies to (startswith).
# line_matcher: None => every line in matching files is compliant;
#               regex => only lines matching the regex are compliant.
# ---------------------------------------------------------------
WHITELIST = [
    # Product UI copy: bilingual locales (zh-CN values + en values such as the zh language label)
    ("src/i18n/locales/", None),
    # Published data artifacts (public/data/latest/*, metadata/*)
    ("public/data/", None),
    # Bilingual test fixtures
    ("tests/fixtures/", None),
    # Product's Chinese doc + Chinese glossary (en counterpart exists)
    ("README.zh-CN.md", None),
    ("docs/glossary.md", None),
    # format.ts bilingual formatter vocabularies (data values, not copy)
    ("src/lib/format.ts", re.compile(r"(zh-CN.*(上涨|下跌|百分位|美元|人民币|港元|韩元))|(\$\{num\}百分位)|(CURRENCY_WORDS)")),
    # universe.ts A-share company names (proper nouns / data values)
    ("src/config/universe.ts", re.compile(r"name:\s*\"" )),
    # YAML data values: label / note / name_zh / disclaimer / name / keyword list items
    ("config/", re.compile(r"(\blabel:|name_zh:|note:|disclaimer:|name:|^\s*- )")),
    # build_prompt zh-CN AI template (prompt data consumed by the analysis pipeline)
    ("pipeline/analysis/build_prompt.py", None),
    # market.py sector label_zh data values
    ("pipeline/collectors/market.py", re.compile(r"label_zh=")),
    # news.py asset keyword lists (Chinese keywords for news matching)
    ("pipeline/collectors/news.py", None),
    # akshare_provider.py Chinese column names from the AKShare API
    ("pipeline/providers/akshare_provider.py", re.compile(r"row\.get\(\"")),
    # tests i18n value assertions (assert zh-CN strings inside quotes or regex literals; comments are still violations)
    ("tests/", re.compile(r"([\"'][^\"']*[\u4e00-\u9fff])|(/[^/\"']*[\u4e00-\u9fff][^/\"']*/)")),
    # index.html bilingual browser shell (title/meta product copy)
    ("index.html", re.compile(r"content=|title")),
    # scan-cn.sh itself: CJK characters are regex/data matching patterns (by design), not copy
    ("scripts/scan-cn.sh", None),
]

def classify(path, line):
    """Return (is_compliant, category) for a (path, line)."""
    for prefix, matcher in WHITELIST:
        if path.startswith(prefix):
            if matcher is None or matcher.search(line):
                return True, prefix
    return False, None

def collect_files():
    if targets:
        files = []
        for t in targets:
            if os.path.isfile(t):
                files.append(t)
            else:
                for dp, dns, fns in os.walk(t):
                    dns[:] = [d for d in dns if d not in {".git", "node_modules", "dist", ".venv", "__pycache__", ".playwright-cli", ".workbuddy"}]
                    for fn in fns:
                        files.append(os.path.join(dp, fn))
        return sorted(files)
    out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=False).stdout
    files = [f for f in out.decode("utf-8", errors="ignore").split("\0") if f]
    return sorted(f for f in files if not re.search(r"(node_modules|^dist/|\.workbuddy|package-lock\.json|yarn\.lock|pnpm-lock\.yaml)", f))

violations = []
compliant = {}  # category -> count
total_lines = 0
for path in collect_files():
    try:
        data = open(path, "r", encoding="utf-8", errors="ignore").read()
    except OSError:
        continue
    for i, line in enumerate(data.splitlines(), 1):
        if not CJK.search(line):
            continue
        total_lines += 1
        is_c, cat = classify(path, line)
        if is_c:
            compliant[cat] = compliant.get(cat, 0) + 1
        else:
            violations.append(f"{path}:{i}: {line}")

print("== Violations (must be 0) ==")
for v in violations:
    print(v)
print(f"-- violations: {len(violations)} --")
print("== Compliant Chinese lines (intentionally bilingual / data values) ==")
for cat, n in sorted(compliant.items(), key=lambda kv: (-kv[1], kv[0])):
    print(f"  {n:5d}  {cat}")
print(f"-- compliant total: {sum(compliant.values())} (scanned {total_lines} Chinese line(s)) --")

sys.exit(1 if violations else 0)
PYEOF
