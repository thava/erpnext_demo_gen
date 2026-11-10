"""Snapshots: a demo site in under a minute instead of a live install (design 5.10, DEC-27).

A snapshot is a disposable demo site: a database dump made with Frappe's own backup
API plus a manifest. It is built on a throwaway site with one company (the demo
company, created by the setup wizard) and restored only as a new site with
`bench new-site --source-sql`; nothing existing is touched.

The commands drive `bench` itself in subprocesses (new-site, install, verify,
drop-site), so each step runs exactly as a user would run it. Steps that need a
connected site (`complete_setup`, `dump`) are module functions run through
`bench --site X execute`.
"""

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
from random import Random

import frappe
from frappe.utils import get_bench_path, getdate, now

SNAPSHOT_DIR = "demo-snapshots"  # under the bench folder, outside sites/
ADMIN_PASSWORD = "changeme"  # documented; snapshots hold only open, fictional data
def apps_for(pack_id: str) -> tuple[str, ...]:
	"""Apps a build site for the pack gets, in install order (India: india_compliance too)."""
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import load_pack

	return tuple(dict.fromkeys(("frappe", "erpnext", *get_locale(load_pack(pack_id)).required_apps, "erpnext_demo_gen")))


class SnapshotError(Exception):
	"""A refusal or failure with a message meant for the user."""


# ---------------------------------------------------------------- versions
def parse_version(text: str) -> tuple[int, int, int]:
	"""(major, minor, patch) from versions such as "16.54.0" or "1.0.0-beta.4"."""
	numbers = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
	major, minor, patch = (numbers + [0, 0, 0])[:3]
	return major, minor, patch


def version_action(app: str, snapshot: str, bench: str) -> tuple[str, str]:
	"""What restoring needs for one app: ("same" | "migrate" | "refuse", reason).

	Same major and not newer than the bench: restore (and migrate when older).
	Newer at any level is a downgrade; a different major would not be the data
	this bench's generator makes. Either way, build a snapshot on this bench.
	"""
	s, b = parse_version(snapshot), parse_version(bench)
	if s == b:
		return "same", ""
	if s[0] != b[0]:
		return "refuse", f"{app} {snapshot} in the snapshot, {bench} on this bench: a different major version"
	if s > b:
		return "refuse", f"{app} {snapshot} in the snapshot is newer than {bench} on this bench"
	return "migrate", f"{app} {snapshot} -> {bench}"


def bench_versions() -> dict[str, str]:
	"""Version of every app in the bench (sites/apps.txt), read without a site."""
	import importlib

	versions = {}
	for app in frappe.get_all_apps(with_internal_apps=False, sites_path=os.path.join(bench_path(), "sites")):
		try:
			versions[app] = str(importlib.import_module(app).__version__)
		except Exception:
			continue
	return versions


def app_commit(app: str) -> str | None:
	try:
		path = frappe.get_app_path(app, "..")
		out = subprocess.run(["git", "-C", path, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
		dirty = subprocess.run(["git", "-C", path, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True)
		return (out.stdout.strip() + ("-dirty" if dirty.stdout.strip() else "")) or None
	except Exception:
		return None


# ---------------------------------------------------------------- paths and bench
def bench_path() -> str:
	return os.path.abspath(get_bench_path())


def default_dir() -> str:
	return os.path.join(bench_path(), SNAPSHOT_DIR)


def bench(args: list[str], log=print, check=True, secret: str | None = None) -> subprocess.CompletedProcess:
	"""Run `bench ...` from the bench folder, streaming its output."""
	shown = " ".join(a if a != secret else "***" for a in args)
	log(f"$ bench {shown}")
	result = subprocess.run([shutil.which("bench") or "bench", *args], cwd=bench_path())
	if check and result.returncode:
		raise SnapshotError(f"`bench {shown}` failed with exit code {result.returncode}")
	return result


def find_file(path: str) -> str:
	"""bench runs commands from sites/; resolve a relative path against the shell's
	working directory ($PWD) first, then the bench folder and its snapshot folder."""
	if os.path.isabs(path):
		return path
	for base in (os.environ.get("PWD"), bench_path(), default_dir(), os.getcwd()):
		if base and os.path.exists(os.path.join(base, path)):
			return os.path.abspath(os.path.join(base, path))
	raise SnapshotError(f"No such file: {path}")


def sha256(path: str) -> str:
	digest = hashlib.sha256()
	with open(path, "rb") as f:
		for chunk in iter(lambda: f.read(1 << 20), b""):
			digest.update(chunk)
	return digest.hexdigest()


def manifest_path(dump: str) -> str:
	return re.sub(r"\.sql\.gz$", "", dump) + ".json"


# ---------------------------------------------------------------- build
def build(
	pack: str,
	size: str,
	seed: int,
	end_date: str | None,
	db_root_password: str,
	host_scope: str | None,
	out_dir: str | None,
	log=print,
) -> str:
	"""Build a snapshot on a throwaway site; returns the dump's path."""
	from erpnext_demo_gen.packs import load_pack

	load_pack(pack)  # fails early on an unknown pack
	from erpnext_demo_gen.packs import list_packs

	info = next(p for p in list_packs() if p["id"] == pack)
	label = f"{info['pack']}-{info['country']}"  # e.g. furniture_store-US
	site = f"demo-snapshot-{label}-{size}.localhost".replace("_", "-").lower()
	if os.path.exists(os.path.join(bench_path(), "sites", site)):
		raise SnapshotError(
			f"Build site {site} exists, probably from a failed build. Drop it first: "
			f"bench drop-site {site} --no-backup"
		)
	out_dir = os.path.abspath(out_dir or default_dir())
	os.makedirs(out_dir, exist_ok=True)

	new_site = ["new-site", site, "--admin-password", ADMIN_PASSWORD, "--db-root-password", db_root_password]
	if host_scope:
		new_site += ["--mariadb-user-host-login-scope", host_scope]
	for app in apps_for(pack)[1:]:
		new_site += ["--install-app", app]
	bench(new_site, log, secret=db_root_password)
	try:
		bench(["--site", site, "execute", "erpnext_demo_gen.snapshot.complete_setup", "--kwargs", json.dumps({"pack": pack, "seed": seed})], log)
		install = ["--site", site, "demo-gen", "install", "--country", info["country"], "--pack", info["pack"]]
		install += ["--size", size, "--seed", str(seed)]
		from erpnext_demo_gen.locales import get_locale

		install += ["--use-wizard-company", *get_locale(load_pack(pack)).snapshot_install_args]
		install += ["--end-date", end_date] if end_date else []
		bench(install, log)
		bench(["--site", site, "demo-gen", "verify"], log)
		bench(["--site", site, "execute", "erpnext_demo_gen.snapshot.dump", "--kwargs", json.dumps({"out_dir": out_dir})], log)
	except SnapshotError as e:
		raise SnapshotError(f"{e}. The build site {site} is kept for inspection; drop it with: bench drop-site {site} --no-backup") from e
	dump = latest_dump(out_dir, label, size)
	# The build queued background jobs (site setup, install); without workers they pile
	# up until the queue refuses new ones (F-30), and with workers they would run against
	# a dropped site. They belong to this throwaway site, so remove them with it.
	bench(["purge-jobs", "--site", site], log, check=False)
	bench(["drop-site", site, "--no-backup", "--force", "--db-root-password", db_root_password], log, secret=db_root_password)
	return dump


def latest_dump(out_dir: str, label: str, size: str) -> str:
	dumps = sorted(
		(f for f in os.listdir(out_dir) if f.startswith(f"demo-{label}-{size}-") and f.endswith(".sql.gz")),
		key=lambda f: os.path.getmtime(os.path.join(out_dir, f)),
	)
	if not dumps:
		raise SnapshotError(f"No snapshot was written to {out_dir}")
	return os.path.join(out_dir, dumps[-1])


def company_identity(pack_id: str, seed: int) -> tuple[str, str]:
	"""The name and abbreviation a live install would generate for this seed."""
	from erpnext_demo_gen import naming
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import load_pack

	pack = load_pack(pack_id)
	name = get_locale(pack).company_name(Random(f"{seed}:company-name"), pack["company"]["industry_nouns"])
	return name, naming.abbreviation(name, set())


def fiscal_year(today: dt.date, locale=None) -> tuple[dt.date, dt.date]:
	"""The fiscal year containing today (the locale's; India: April to March)."""
	from erpnext_demo_gen.locales import get_locale

	locale = locale or get_locale()
	start = locale.fiscal_year_starts(today, today)[0]
	return start, locale.fiscal_year_end(start)


def complete_setup(pack: str, seed: int = 1, company: str | None = None):
	"""Run the setup wizard non-interactively in the pack's country (India: INR) with the
	demo company, or with the given company (CI: a neutral wizard company next to the
	demo's own)."""
	from frappe.desk.page.setup_wizard.setup_wizard import setup_complete

	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import load_pack

	locale = get_locale(load_pack(pack))

	if frappe.is_setup_complete():
		return
	if company:
		from erpnext_demo_gen import naming

		name, abbr = company, naming.abbreviation(company, set())
	else:
		name, abbr = company_identity(pack, int(seed))
	start, end = fiscal_year(dt.date.today(), locale)
	result = setup_complete(
		{
			"language": "English",
			"country": locale.country,
			"timezone": locale.timezone,
			"currency": locale.currency,
			"company_name": name,
			"company_abbr": abbr,
			"chart_of_accounts": locale.wizard_chart,
			"fy_start_date": str(start),
			"fy_end_date": str(end),
		}
	)
	frappe.db.commit()
	if not frappe.is_setup_complete():
		raise SnapshotError(f"The setup wizard did not complete: {result}")
	print(f"Setup complete: {name} ({abbr})")


def dump(out_dir: str):
	"""Back up the build site with Frappe's backup API and write the manifest beside it."""
	from frappe.utils.backups import new_backup

	from erpnext_demo_gen.registry import Run

	run_name = frappe.get_all(
		"Demo Data Run", filters={"status": "Completed"}, pluck="name", order_by="creation desc", limit=1
	)
	if not run_name:
		raise SnapshotError("No completed demo run on the build site")
	run = Run(run_name[0])
	params = run.params
	versions = {app: str(frappe.get_attr(f"{app}.__version__")) for app in frappe.get_installed_apps()}
	short = {"frappe": "f", "erpnext": "e", "india_compliance": "ic", "erpnext_demo_gen": "dd"}
	tag = "-".join(f"{short.get(a, a)}{versions[a]}" for a in apps_for(params.pack))
	from erpnext_demo_gen.packs import list_packs

	info = next(p for p in list_packs() if p["id"] == params.pack)
	label = f"{info['pack']}-{info['country']}"
	base = os.path.join(out_dir, f"demo-{label}-{params.size}-s{params.seed}-{tag}-{dt.date.today():%Y%m%d}")

	odb = new_backup(ignore_files=True, ignore_conf=True, compress=True, force=True, backup_path_db=f"{base}.sql.gz")
	path = odb.backup_path_db
	from erpnext_demo_gen.setup.company import date_range

	start, end = date_range(getdate(params.end_date), params.months)
	manifest = {
		"format": 1,
		"pack": params.pack,
		"pack_name": info["pack"],
		"country": info["country"],
		"pack_version": params.pack_version,
		"size": params.size,
		"seed": params.seed,
		"company": run.doc.company,
		"data_from": str(start),
		"data_to": str(end),
		"built_at": now(),
		"apps": {app: {"version": versions[app], "commit": app_commit(app)} for app in frappe.get_installed_apps()},
		"mariadb": frappe.db.sql("select version()")[0][0],
		"documents": run.totals(),
		"admin_password": ADMIN_PASSWORD,
		"dump": os.path.basename(path),
		"sha256": sha256(path),
	}
	with open(manifest_path(path), "w") as f:
		json.dump(manifest, f, indent=1)
	print(f"Snapshot: {path}")


# ---------------------------------------------------------------- new site
def check(dump_path: str) -> tuple[dict, list[str]]:
	"""Manifest, checksum and version policy. Returns (manifest, apps that need a migrate)."""
	if not os.path.exists(dump_path):
		raise SnapshotError(f"No such file: {dump_path}")
	mpath = manifest_path(dump_path)
	if not os.path.exists(mpath):
		raise SnapshotError(f"The manifest {mpath} is missing; it must sit next to the dump")
	with open(mpath) as f:
		manifest = json.load(f)
	if sha256(dump_path) != manifest["sha256"]:
		raise SnapshotError(f"{dump_path} does not match its manifest (checksum differs); the file is damaged or replaced")
	ours = bench_versions()
	refusals, migrations = [], []
	for app, info in manifest["apps"].items():
		if app not in ours:
			refusals.append(f"{app} {info['version']} is not on this bench (bench get-app {app})")
			continue
		action, reason = version_action(app, info["version"], ours[app])
		if action == "refuse":
			refusals.append(reason)
		elif action == "migrate":
			migrations.append(reason)
	if refusals:
		raise SnapshotError(
			"This snapshot does not fit this bench:\n  " + "\n  ".join(refusals)
			+ "\nBuild one here instead: bench demo-gen snapshot build --pack ... --size ..."
		)
	return manifest, migrations


def new_site(
	name: str,
	dump_path: str,
	admin_password: str | None,
	db_root_password: str,
	host_scope: str | None,
	log=print,
):
	dump_path = os.path.abspath(dump_path)
	manifest, migrations = check(dump_path)
	log(
		f"Snapshot {manifest['pack']}/{manifest['size']} seed {manifest['seed']}, built {manifest['built_at'][:10]}; "
		f"data from {manifest['data_from']} to {manifest['data_to']}; company {manifest['company']}"
	)
	if os.path.exists(os.path.join(bench_path(), "sites", name)):
		raise SnapshotError(f"Site {name} already exists; snapshots are restored only as new sites")
	cmd = ["new-site", name, "--source-sql", dump_path, "--db-root-password", db_root_password]
	cmd += ["--admin-password", admin_password or ADMIN_PASSWORD]
	if host_scope:
		cmd += ["--mariadb-user-host-login-scope", host_scope]
	bench(cmd, log, secret=db_root_password)
	if migrations:
		log("Migrating: " + "; ".join(migrations))
		bench(["--site", name, "migrate"], log)
	if admin_password:  # a restore keeps the snapshot's password; set the new one explicitly
		bench(["--site", name, "set-admin-password", admin_password], log, secret=admin_password)
	bench(["--site", name, "demo-gen", "verify"], log)
	log(
		f"Site {name} is ready. Log in as Administrator with "
		+ ("the password you set." if admin_password else f"the password {ADMIN_PASSWORD!r}; change it.")
		+ f" Drop it when done: bench drop-site {name}"
	)
