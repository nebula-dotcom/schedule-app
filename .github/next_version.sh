#!/usr/bin/env bash
# Menghitung nomor versi berikutnya dari tag terakhir (tanpa tag = 1.0.0).
# Pemakaian:  bash .github/next_version.sh v1.0.9     ->  "1.1.0 1001000"   (versi, kode versi Android)
#
# Tiap angka paling besar 9, lalu naik ke angka di depannya:
#   v1.0.0 -> v1.0.1 -> ... -> v1.0.9 -> v1.1.0 -> ... -> v1.9.9 -> v2.0.0
set -eu

LAST="${1:-}"
if [ -z "$LAST" ]; then
  MA=1; MI=0; PA=0
else
  IFS=. read -r MA MI PA <<< "${LAST#v}"
  MA=$((10#$MA)); MI=$((10#$MI)); PA=$((10#$PA + 1))
  if [ "$PA" -gt 9 ]; then PA=0; MI=$((MI + 1)); fi
  if [ "$MI" -gt 9 ]; then MI=0; MA=$((MA + 1)); fi
fi

# Kode versi Android harus selalu naik; rumus ini naik terus untuk urutan di atas.
echo "$MA.$MI.$PA $((MA * 1000000 + MI * 1000 + PA))"
