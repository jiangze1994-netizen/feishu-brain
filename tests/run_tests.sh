#!/usr/bin/env bash
# 全链路自测：不需要真实飞书账号
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
FIX=tests/fixtures
IDX=$FIX/index

echo "=== 0. 生成假语料 ==="
[ -f "$FIX/raw/manifest.jsonl" ] || $PY tests/make_fixture.py --out "$FIX/raw" --count 420

echo "=== 1. L1 体检 ==="
$PY scripts/inventory.py --raw "$FIX/raw" --out "$IDX/inventory.json"

echo "=== 2. L2 分集 ==="
$PY scripts/cluster.py --inventory "$IDX/inventory.json" --out "$IDX/sets.json" --propose
$PY scripts/cluster.py --inventory "$IDX/inventory.json" --out "$IDX/sets.json" --apply

echo "=== 3. 双链 ==="
$PY scripts/links.py --raw "$FIX/raw" --inventory "$IDX/inventory.json" --out "$IDX/links.json"

echo "=== 4. 出脑 ==="
$PY scripts/build_html.py --index "$IDX" --raw "$FIX/raw" --out "$FIX/brain.html" --owner 测试用户

echo "=== 5. 检索 ==="
$PY scripts/search.py --raw "$FIX/raw" --inventory "$IDX/inventory.json" \
    --sets "$IDX/sets.json" --query "转化率 放量" --top 3

echo "=== 6. 提炼原料 ==="
$PY scripts/distill.py --raw "$FIX/raw" --inventory "$IDX/inventory.json" \
    --sets "$IDX/sets.json" --set S01 --out "$IDX/distill-S01.md" --budget 4000

echo "=== 7. 索引文档（只生成 markdown，不写飞书）==="
$PY scripts/index_doc.py --brain "$FIX" --owner 测试用户 --dry-run | head -12

echo
echo "全部通过 ✓  产物：$FIX/brain.html"
