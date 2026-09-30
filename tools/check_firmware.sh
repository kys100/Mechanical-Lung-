#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cli=${ARDUINO_CLI:-arduino-cli}
"$cli" core list | awk '$1=="arduino:renesas_uno" && $2=="1.6.0" {ok=1} END {exit !ok}'
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
mkdir "$task_build/MechLung"
cp MechLung.ino "$task_build/MechLung/MechLung.ino"
"$cli" compile --fqbn arduino:renesas_uno:unor4wifi --warnings all --build-path "$task_build/build" "$task_build/MechLung"
