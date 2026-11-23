#!/bin/sh
# Build native/libascend_pinch.dylib (macOS trackpad pinch for the map).
# Needs Xcode command line tools. The built library is committed so the app
# runs on Macs without a compiler.
set -e
cd "$(dirname "$0")/../native"
clang -dynamiclib -fobjc-arc -O2 -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
    -framework AppKit -o libascend_pinch.dylib mac_pinch.m
echo "Built $(pwd)/libascend_pinch.dylib"
