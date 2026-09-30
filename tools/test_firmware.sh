#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
task_build=$(mktemp -d)
trap 'rm -rf "$task_build"' EXIT
g++ -std=c++17 -Wall -Wextra -Itests/firmware -I. tests/firmware/test_mech_lung.cpp -o "$task_build/test"
for scenario in geometry tx_zero_capacity tx_disconnect tx_partial_capacity tx_record_order tx_overflow rx_flood_budget watchdog_ownership malformed_frames healthy_schedule micros_wrap fault_budget sfm_crc metadata drop_counter_reset recovery_wait completed_ids final_seq_uint32 query_resync sfm_reinit_count override_resync; do
  "$task_build/test" "$scenario"
done
# Check both the truthful unverified default and an explicitly supplied core ID.
g++ -std=c++17 -Wall -Wextra -DMECH_CORE_ID='"test_verified_core"' -Itests/firmware -I. tests/firmware/test_mech_lung.cpp -o "$task_build/verified-core"
"$task_build/verified-core" metadata
