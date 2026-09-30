#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
g++ -std=c++17 -Wall -Wextra -Itests/firmware -I. tests/firmware/test_mech_lung.cpp -o "$task_build/test"
for scenario in geometry tx_zero_capacity tx_disconnect tx_partial_capacity tx_record_order tx_overflow rx_flood_budget watchdog_ownership malformed_frames healthy_schedule micros_wrap fault_budget sfm_crc metadata drop_counter_reset recovery_wait; do
  "$task_build/test" "$scenario"
done
