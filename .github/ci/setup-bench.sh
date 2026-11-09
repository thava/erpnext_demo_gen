#!/usr/bin/env bash
# Set up a Frappe v16 bench with erpnext, india_compliance and this app, and a site
# with the setup wizard completed. Used by every CI job (.github/workflows/ci.yml).
#
# Expects MariaDB on 127.0.0.1:3306 (root password $DB_ROOT_PASSWORD) and Redis on
# 127.0.0.1:6379, both as service containers. The app's checkout is $GITHUB_WORKSPACE.
set -euo pipefail

BENCH=${BENCH:-$HOME/frappe-bench}
SITE=${SITE:-ci.localhost}
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
bench get-app demo_data "$GITHUB_WORKSPACE" --skip-assets
done_step

step "new site $SITE"
bench new-site "$SITE" --db-root-password "$DB_ROOT_PASSWORD" --admin-password admin \
	--mariadb-user-host-login-scope='%' \
	--install-app erpnext --install-app india_compliance --install-app demo_data
bench --site "$SITE" set-config allow_tests true  # bench run-tests requires it
# a neutral wizard company; the demo installs its own company next to it, as on a real site
bench --site "$SITE" execute demo_data.snapshot.complete_setup \
	--kwargs '{"pack": "furniture_store", "company": "CI Base Company Pvt Ltd"}'
done_step

echo "bench ready: $BENCH, site $SITE"
