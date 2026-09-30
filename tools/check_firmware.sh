#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cli=${ARDUINO_CLI:-arduino-cli}
"$cli" core list | awk '$1=="arduino:renesas_uno" && $2=="1.6.0" {ok=1} END {exit !ok}'
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
mkdir "$task_build/MechLung"
cp MechLung.ino acquisition.h scan_snapshot.h telemetry.h "$task_build/MechLung/"
build_id=$(sha256sum MechLung.ino acquisition.h scan_snapshot.h telemetry.h | sha256sum | cut -d' ' -f1)
"$cli" compile --build-property "compiler.cpp.extra_flags=-DMECH_CORE_ID=\"renesas_uno_1.6.0\" -DMECH_BUILD_ID=\"$build_id\"" --fqbn arduino:renesas_uno:unor4wifi --warnings all --build-path "$task_build/build" "$task_build/MechLung"
