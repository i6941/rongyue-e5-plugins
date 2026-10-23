#!/bin/bash
set -e
ZIG=/home/yaozh/tools/zig/zig
OH=/home/yaozh/build/openh264
SRC=/mnt/d/workspace/Rongyue-E5/native/e5play.c
OUT=/mnt/d/workspace/Rongyue-E5/native/e5play
INC=/mnt/d/workspace/Rongyue-E5/native
$ZIG c++ -x c++ -target aarch64-linux-musl -O2 \
  -I "$INC" -I "$OH/codec/api" \
  -c "$SRC" -o /tmp/e5play.o
$ZIG c++ -target aarch64-linux-musl -O2 -o "$OUT" /tmp/e5play.o "$OH/libopenh264.a" -lpthread
ls -l "$OUT"
