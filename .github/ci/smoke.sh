#!/usr/bin/env bash
# Smoke test one pack and size on a CI site: install, verify, uninstall, compare the
# watched table counts (erpnext_demo_gen.tests.smoke). Fails unless it reports success.
# Usage: smoke.sh COUNTRY PACK SIZE [SEED] [SITE] [EXTRA]   (SITE: ci.localhost; ci-us.localhost for US, ci-ae.localhost for AE, ci-de.localhost for DE)
# EXTRA: more smoke.run keyword arguments, Python syntax, e.g. '"use_wizard_company": True'
set -uo pipefail
country=$1 pack=$2 size=$3 seed=${4:-1} site=${5:-ci.localhost} extra=${6:+, $6}
log=$(mktemp)
bench --site "$site" execute erpnext_demo_gen.tests.smoke.run \
	--kwargs "{\"country\": \"$country\", \"pack\": \"$pack\", \"size\": \"$size\", \"seed\": $seed$extra}" 2>&1 | tee "$log"
grep -q "smoke test passed" "$log"
