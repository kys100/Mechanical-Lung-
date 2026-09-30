#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
g++ -std=c++17 -Wall -Wextra -Itests/firmware -I. tests/firmware/test_mech_lung.cpp -o "$task_build/test"
"$task_build/test"
