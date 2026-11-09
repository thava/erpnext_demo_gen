#!/usr/bin/env bash
# Smoke test one pack and size on the CI site: install, verify, uninstall, compare the
# watched table counts (demo_data.tests.smoke). Fails unless it reports success.
set -uo pipefail
pack=$1 size=$2 seed=${3:-1}
log=$(mktemp)
bench --site ci.localhost execute demo_data.tests.smoke.run \
	--kwargs "{\"pack\": \"$pack\", \"size\": \"$size\", \"seed\": $seed}" 2>&1 | tee "$log"
grep -q "smoke test passed" "$log"
