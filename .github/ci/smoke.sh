#!/usr/bin/env bash
# Smoke test one pack and size on a CI site: install, verify, uninstall, compare the
# watched table counts (demo_data.tests.smoke). Fails unless it reports success.
# Usage: smoke.sh COUNTRY PACK SIZE [SEED] [SITE]   (SITE: ci.localhost; ci-us.localhost for US, ci-ae.localhost for AE)
set -uo pipefail
country=$1 pack=$2 size=$3 seed=${4:-1} site=${5:-ci.localhost}
log=$(mktemp)
bench --site "$site" execute demo_data.tests.smoke.run \
	--kwargs "{\"country\": \"$country\", \"pack\": \"$pack\", \"size\": \"$size\", \"seed\": $seed}" 2>&1 | tee "$log"
grep -q "smoke test passed" "$log"
