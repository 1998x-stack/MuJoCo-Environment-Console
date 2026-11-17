#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PARTS="$ROOT/release/source-parts"
OUT="$ROOT/release/mujoco-console-source.tar.xz"
mkdir -p "$ROOT/release"
test -f "$PARTS/part-01.bin"
test -f "$PARTS/part-02a.bin"
test -f "$PARTS/part-02b.bin"

# part-01 contains base64-decoded chunks 0, 1, 3 and 4.
# Reinsert the two decoded halves of chunk 2 between chunks 1 and 3.
head -c 12000 "$PARTS/part-01.bin" > "$OUT"
cat "$PARTS/part-02a.bin" "$PARTS/part-02b.bin" >> "$OUT"
tail -c +12001 "$PARTS/part-01.bin" >> "$OUT"

expected="2721a58736c66bc79bdce5384c217d6afd7ef46fcd3bf445899f5f7475964fed"
actual="$(sha256sum "$OUT" | awk '{print $1}')"
if [[ "$actual" != "$expected" ]]; then
  echo "Archive checksum mismatch: $actual" >&2
  rm -f "$OUT"
  exit 1
fi
xz -t "$OUT"
echo "Verified source archive: $OUT"
echo "SHA-256: $actual"
