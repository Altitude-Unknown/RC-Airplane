#!/bin/sh
# Build native/libascend_mac.dylib (macOS trackpad pinch and the computer's location).
# Needs Xcode command line tools. The built library is committed so the app
# runs on Macs without a compiler.
set -e
cd "$(dirname "$0")/../native"
clang -dynamiclib -fobjc-arc -O2 -arch arm64 -arch x86_64 -mmacosx-version-min=11.0 \
    -framework AppKit -framework CoreLocation -o libascend_mac.dylib ascend_mac.m
echo "Built $(pwd)/libascend_mac.dylib"
