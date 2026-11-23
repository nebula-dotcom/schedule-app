#!/usr/bin/env bash
# Hitung nomor versi berikutnya dari tag terakhir
set -eu

# Tag terakhir dan hitungan versi
LAST="${1:-}"
if [ -z "$LAST" ]; then
  MA=1; MI=0; PA=0
else
  IFS=. read -r MA MI PA <<< "${LAST#v}"
  MA=$((10#$MA)); MI=$((10#$MI)); PA=$((10#$PA + 1))
  if [ "$PA" -gt 9 ]; then PA=0; MI=$((MI + 1)); fi
  if [ "$MI" -gt 9 ]; then MI=0; MA=$((MA + 1)); fi
fi

# Cetak versi dan kode versi Android
echo "$MA.$MI.$PA $((MA * 1000000 + MI * 1000 + PA))"
