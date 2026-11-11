#!/usr/bin/env bash
# Set up a Frappe v16 bench with erpnext, india_compliance and this app, and four sites
# with the setup wizard completed: $SITE (India, with india_compliance), $US_SITE (United
# States), $AE_SITE (United Arab Emirates) and $DE_SITE (Germany, SKR04 chart); the last
# three have erpnext and this app only. Used by every CI job (.github/workflows/ci.yml).
# SKIP_SITES=1 stops after the apps (release.yml: snapshot build makes its own sites).
#
# Expects MariaDB on 127.0.0.1:3306 (root password $DB_ROOT_PASSWORD) and Redis on
# 127.0.0.1:6379, both as service containers. The app's checkout is $GITHUB_WORKSPACE.
set -euo pipefail

BENCH=${BENCH:-$HOME/frappe-bench}
SITE=${SITE:-ci.localhost}
US_SITE=${US_SITE:-ci-us.localhost}
AE_SITE=${AE_SITE:-ci-ae.localhost}
DE_SITE=${DE_SITE:-ci-de.localhost}
BRANCH=${FRAPPE_BRANCH:-version-16}
DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-root}

step() { echo "::group::$*"; }
done_step() { echo "::endgroup::"; }

step "bench init (frappe $BRANCH)"
pip install --quiet frappe-bench
bench init "$BENCH" --frappe-branch "$BRANCH" --skip-assets --skip-redis-config-generation \
	--python "$(command -v python)" --no-procfile
cd "$BENCH"
# one Redis serves both cache and queue; Transaction Deletion Record needs the queue reachable
bench set-config -g db_host 127.0.0.1
bench set-config -g redis_cache redis://127.0.0.1:6379
bench set-config -g redis_queue redis://127.0.0.1:6379
bench set-config -g redis_socketio redis://127.0.0.1:6379
done_step

step "get apps"
bench get-app erpnext --branch "$BRANCH" --skip-assets
bench get-app india_compliance https://github.com/resilient-tech/india-compliance --branch "$BRANCH" --skip-assets
bench get-app erpnext_demo_gen "$GITHUB_WORKSPACE" --skip-assets
done_step

if [ "${SKIP_SITES:-}" = 1 ]; then
	# snapshot builds make their own sites (release workflow)
	echo "bench ready: $BENCH (no sites, SKIP_SITES=1)"
	exit 0
fi

step "new site $SITE"
bench new-site "$SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin \
	--mariadb-user-host-login-scope='%' \
	--install-app erpnext --install-app india_compliance --install-app erpnext_demo_gen
bench --site "$SITE" set-config allow_tests true  # bench run-tests requires it
# a neutral wizard company; the demo installs its own company next to it, as on a real site
bench --site "$SITE" execute erpnext_demo_gen.snapshot.complete_setup \
	--kwargs '{"pack": "furniture_store", "company": "CI Base Company Pvt Ltd"}'
done_step

step "new site $US_SITE"
bench new-site "$US_SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin \
	--mariadb-user-host-login-scope='%' \
	--install-app erpnext --install-app erpnext_demo_gen
bench --site "$US_SITE" set-config allow_tests true
bench --site "$US_SITE" execute erpnext_demo_gen.snapshot.complete_setup \
	--kwargs '{"pack": "furniture_store_us", "company": "CI Base Company LLC"}'
done_step

step "new site $AE_SITE"
bench new-site "$AE_SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin \
	--mariadb-user-host-login-scope='%' \
	--install-app erpnext --install-app erpnext_demo_gen
bench --site "$AE_SITE" set-config allow_tests true
bench --site "$AE_SITE" execute erpnext_demo_gen.snapshot.complete_setup \
	--kwargs '{"pack": "furniture_store_ae", "company": "CI Base Company LLC"}'
done_step

step "new site $DE_SITE"
bench new-site "$DE_SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin \
	--mariadb-user-host-login-scope='%' \
	--install-app erpnext --install-app erpnext_demo_gen
bench --site "$DE_SITE" set-config allow_tests true
bench --site "$DE_SITE" execute erpnext_demo_gen.snapshot.complete_setup \
	--kwargs '{"pack": "furniture_store_de", "company": "CI Base Company GmbH"}'
done_step

echo "bench ready: $BENCH, sites $SITE, $US_SITE, $AE_SITE and $DE_SITE"
