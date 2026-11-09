#!/usr/bin/env bash
# Smoke test one pack and size on a CI site: install, verify, uninstall, compare the
# watched table counts (demo_data.tests.smoke). Fails unless it reports success.
# Usage: smoke.sh PACK SIZE [SEED] [SITE]   (SITE: ci.localhost, or ci-us.localhost for US packs)
set -uo pipefail
pack=$1 size=$2 seed=${3:-1} site=${4:-ci.localhost}
log=$(mktemp)
bench --site "$site" execute demo_data.tests.smoke.run \
	--kwargs "{\"pack\": \"$pack\", \"size\": \"$size\", \"seed\": $seed}" 2>&1 | tee "$log"
grep -q "smoke test passed" "$log"
