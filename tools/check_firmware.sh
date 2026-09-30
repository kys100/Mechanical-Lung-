#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cli=${ARDUINO_CLI:-arduino-cli}
"$cli" core list | awk '$1=="arduino:renesas_uno" && $2=="1.6.0" {ok=1} END {exit !ok}'
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
mkdir "$task_build/MechLung"
cp MechLung.ino "$task_build/MechLung/MechLung.ino"
build_id=$(sha256sum MechLung.ino | cut -d' ' -f1)
"$cli" compile --build-property "compiler.cpp.extra_flags=-DMECH_BUILD_ID=\"$build_id\"" --fqbn arduino:renesas_uno:unor4wifi --warnings all --build-path "$task_build/build" "$task_build/MechLung"
