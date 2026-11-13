"""bench --site <site> demo-gen ...

    demo-gen list-packs
    demo-gen install --country IN|US|AE|DE [--pack furniture_store] [--size small|medium|large] [--seed N] [--end-date YYYY-MM-DD]
                      [--home-state TN] [--demo-company-name NAME] [--use-wizard-company]
                      [--unregistered] [--force]
    demo-gen status
    demo-gen history [--run DD-RUN-00001] [--limit 10]
    demo-gen verify [--run DD-RUN-00001]
    demo-gen uninstall [--run DD-RUN-00001] [--registry-only] [--no-backup]
    demo-gen snapshot build --country IN|US|AE|DE [--pack furniture_store] [--size medium] [--seed N]
    demo-gen snapshot new-site NAME DUMP.sql.gz [--admin-password PW]

Thin wrappers over erpnext_demo_gen.service (M-13).
"""

import click
from frappe.commands import get_site, pass_context

from erpnext_demo_gen.packs import SIZES


COUNTRY_HELP = 'Country of the demo (required): IN, US, AE or DE, or the name, e.g. India, "United States", UAE, Germany (case, spaces and hyphens ignored)'
PACK_HELP = "Pack name (see list-packs). Default: the country's default pack"


def _connect(context):
	import frappe

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	frappe.flags.mute_emails = True
	return site


def _run(context, fn):
	import frappe

	from erpnext_demo_gen.packs import PackError
	from erpnext_demo_gen.service import DemoDataError

	_connect(context)
	try:
		return fn()
	except (DemoDataError, PackError) as e:
		raise click.ClickException(str(e)) from e
	finally:
		frappe.destroy()


@click.group("demo-gen")
def demo_gen():
	"""Install, check and remove realistic demo data for ERPNext: India, the US (Texas), the UAE and Germany.

	install and snapshot build need --country (IN, US, AE or DE; no default, so the country
	is always a deliberate choice); --pack is optional (the country's default pack).
	India: INR prices, customers and suppliers with GSTINs, GST through india_compliance
	(which must be installed); --unregistered --force for a business not registered for GST.
	US: a Texas business selling in Texas, USD, sales and use tax.
	AE: a VAT-registered Dubai business, AED, 5% VAT (ERPNext's UAE VAT 201 report).
	DE: a Munich GmbH, EUR, SKR04 chart, 19% / 7% VAT (ERPNext's German tax templates).
	--unregistered --force: no sales tax, purchase tax is a cost (IN; AE below the VAT
	threshold; DE Kleinunternehmer). Refused for the US.
	--use-wizard-company needs the default company in that country and currency.
	"""


@demo_gen.command("list-packs")
def list_packs():
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import default_packs
	from erpnext_demo_gen.packs import list_packs as _list

	by_name = {}
	for p in _list():
		by_name.setdefault(p["pack"], []).append(p)
	click.echo(f"{'Pack':<24} {'Countries':<10} {'Sizes':<22} Title")
	for name in sorted(by_name):
		versions = by_name[name]
		countries = ", ".join(sorted({v["country"] for v in versions}))
		sizes = ", ".join(s for s in SIZES if any(s in v["sizes"] for v in versions))
		titles = "; ".join(sorted({f"{v['title']}" for v in versions}))
		click.echo(f"{name:<24} {countries:<10} {sizes:<22} {titles}")
	defaults = default_packs()
	click.echo(
		"Default pack per country: "
		+ ", ".join(f"{code} ({get_locale(code).country}) {defaults[code]}" for code in sorted(defaults))
	)


@demo_gen.command("install")
@click.option("--country", required=True, help=COUNTRY_HELP)
@click.option("--pack", help=PACK_HELP)
@click.option(
	"--size",
	default="medium",
	show_default=True,
	type=click.Choice(SIZES),
	help="small: 3 months, about 300 documents, 1 min; medium: 12 months, about 1,200, 5 min; large: 24 months, about 19,000, 1-2 h",
)
@click.option("--seed", default=1, show_default=True, type=int, help="Same seed, same data")
@click.option("--end-date", help="Last day of generated data (default: today)")
@click.option("--home-state", help="State of the demo company: India: name, code (TN, KA) or GST state code (33); US: TX only; UAE: emirate (DU, AZ, SH...). Default: the pack's")
@click.option(
	"--demo-company-name", help="Name for the new demo company (default: generated from the seed)"
)
@click.option(
	"--use-wizard-company",
	is_flag=True,
	help="Generate into the existing default company instead of a new one. "
	"Needs --force only if that company already has transactions",
)
@click.option(
	"--unregistered",
	is_flag=True,
	help="A business not registered for sales tax: none on sales, tax paid on purchases is a cost. "
	"IN, AE and DE (Kleinunternehmer); not US. Needs --force (the demo's turnover is above the threshold)",
)
@click.option(
	"--force",
	is_flag=True,
	help="Needed when: the site already has transactions; the GST API is on; or --unregistered is used",
)
@click.option("--verbose", is_flag=True, help="At the end, list what was created per doctype")
@pass_context
def install(
	context,
	country,
	pack,
	size,
	seed,
	end_date,
	home_state,
	demo_company_name,
	use_wizard_company,
	unregistered,
	force,
	verbose,
):
	"""Install demo data. Re-running the same command resumes an interrupted install."""
	from erpnext_demo_gen import service

	def go():
		run = service.install(
			pack,
			size,
			seed,
			end_date,
			home_state,
			demo_company_name,
			use_wizard_company,
			force,
			log=_log,
			unregistered=unregistered,
			country=country,
		)
		_log(f"{run.name} completed: {_documents(run.totals())} in {run.doc.company}{_took(run)}")
		if verbose:
			_counts_table(run.counts())
		click.echo("Check it with: demo-gen verify. Remove it with: demo-gen uninstall.")

	_run(context, go)


@demo_gen.command("status")
@pass_context
def status(context):
	"""What is installed now, in short. See history for past runs."""
	from erpnext_demo_gen import service

	def go():
		s = service.status()
		if not s["runs"]:
			click.echo("No demo data runs on this site")
			return
		for r in s["active"]:
			click.echo(f"{r.name}  {r.status}: {_describe(r)}")
			click.echo(f"    {_documents(r['totals'])}; since {_when(r.finished_at or r.started_at)}")
		if not s["active"]:
			last = s["latest"]
			click.echo(f"No demo data installed (last run {last.name}, {last.status.lower()} {_when(last.finished_at)})")
		parts = ", ".join(f"{n} {st.lower()}" for st, n in sorted(s["by_status"].items()))
		click.echo(f"Runs on this site: {s['runs']} ({parts}). Details: demo-gen history")

	_run(context, go)


@demo_gen.command("history")
@click.option("--run", "run_name", help="Only this run, plus what it created per doctype")
@click.option("--limit", default=20, show_default=True, help="Number of events to show")
@pass_context
def history(context, run_name, limit):
	"""Install and uninstall events of all runs, newest first."""
	from erpnext_demo_gen import service

	def go():
		runs = service.history(run_name)
		if not runs:
			click.echo("No demo data runs on this site")
			return
		timeline = []
		for r in runs:
			for i, (at, text, starts_install) in enumerate(_events(r["events"])):
				if starts_install:
					text += f": {_details(r)}"
				timeline.append((at, r.name, i, text))  # i orders events within the same second
		timeline.sort(key=lambda t: t[:3], reverse=True)
		for at, name, _, text in timeline[:limit]:
			click.echo(f"{_when(at)}  {name}  {text}")
		if len(timeline) > limit:
			click.echo(f"... {len(timeline) - limit} older events (--limit)")
		if run_name:
			r = runs[0]
			click.echo(f"\n{r.name} is {r.status.lower()} now.")
			_doctype_table(r["installed"], r["current"])

	_run(context, go)


def _details(r) -> str:
	"""What the run generates. The data period ends on end_date; it is not an event time."""
	months = f"{r.months} months of data" if r.get("months") else "data"
	return f"{_pack(r)}/{r.size} seed {r.seed}, {months} up to {r.end_date}, company {r.company or '-'}"


def _pack(r) -> str:
	"""The run's pack with its country, e.g. "furniture_store (US)"."""
	from erpnext_demo_gen.packs import describe

	return describe(r.pack)


def _describe(r) -> str:
	return f"{_pack(r)}/{r.size} seed {r.seed}, data up to {r.end_date}, company {r.company or '-'}"


def _when(value) -> str:
	return str(value)[:16] if value else "-"


PRESENT = ("Created", "Submitted", "Reused")


def _documents(totals: dict) -> str:
	text = f"{sum(totals.get(s, 0) for s in PRESENT)} documents"
	problems = {s: totals[s] for s in ("Failed", "Skipped") if totals.get(s)}
	if problems:
		text += " (" + ", ".join(f"{n} {s.lower()}" for s, n in problems.items()) + ")"
	return text


def _events(events: list[dict]) -> list[tuple[str, str, bool]]:
	"""(time, text, starts an install) for each status change, labelled by what it means."""
	from frappe.utils import get_datetime

	out, phase, started = [], "install", None
	for e in events:
		st = e["status"]
		first = False
		if st == "Running":
			first = phase == "install" and started is None
			label = "install started" if first else "install resumed"
			phase, started = "install", e["at"]
		elif st == "Uninstalling":
			label, phase, started = "uninstall started", "uninstall", e["at"]
		elif st == "Completed":
			label = "installed"
		elif st == "Uninstalled":
			label = "uninstalled"
		else:
			label = f"{phase} failed"
		text = label
		if st in ("Completed", "Uninstalled", "Failed") and started:
			seconds = (get_datetime(e["at"]) - get_datetime(started)).total_seconds()
			text += f" after {_duration(seconds)}"
		if e.get("documents"):
			text += " (" + ", ".join(f"{s} {n}" for s, n in sorted(e["documents"].items())) + ")"
		if e.get("error"):
			text += f": {e['error']}"
		out.append((e["at"], text, first))
	return out


def _duration(seconds: float) -> str:
	from erpnext_demo_gen.progress import duration

	return duration(seconds)


def _log(message: str):
	"""Echo with a timestamp, so each step shows when it happened."""
	import datetime

	import frappe
	from frappe.utils import now_datetime

	# the site's time zone when connected; snapshot commands run without a site
	when = now_datetime() if getattr(frappe.local, "conf", None) and frappe.db else datetime.datetime.now()
	click.echo(f"{when:%Y-%m-%d %H:%M:%S}  {message}")


def _took(run) -> str:
	"""Time since the latest start (install or uninstall), e.g. " after 4 min"."""
	from frappe.utils import get_datetime, now_datetime

	starts = [e["at"] for e in run.events() if e["status"] in ("Running", "Uninstalling")]
	if not starts:
		return ""
	return f" after {_duration((now_datetime() - get_datetime(starts[-1])).total_seconds())}"


def _counts_table(counts: dict):
	click.echo(f"    {'Doctype':<28} Documents")
	for doctype, states in sorted(counts.items()):
		click.echo(f"    {doctype:<28} " + ", ".join(f"{s} {n}" for s, n in sorted(states.items())))


def _doctype_table(installed: dict, current: dict):
	click.echo(f"    {'Doctype':<28} {'Installed':<26} Now")
	for doctype in sorted(set(installed) | set(current)):
		fmt = lambda states: ", ".join(f"{s} {n}" for s, n in sorted((states or {}).items())) or "-"  # noqa: E731
		click.echo(f"    {doctype:<28} {fmt(installed.get(doctype)):<26} {fmt(current.get(doctype))}")


@demo_gen.command("verify")
@click.option("--run", "run_name", help="Run to check (default: the latest completed run)")
@pass_context
def verify(context, run_name):
	"""Check ledgers, aging, stock, registry and screen coverage. Exits 1 if any check fails."""
	from erpnext_demo_gen import service

	def go():
		run, checks = service.verify(run_name)
		click.echo(f"{run.name} ({run.doc.company})")
		for c in checks:
			mark = click.style("ok  ", fg="green") if c.ok else click.style("FAIL", fg="red")
			click.echo(f"  {mark} {c.name}: {c.detail}")
		failed = [c for c in checks if not c.ok]
		click.echo(f"{len(checks) - len(failed)}/{len(checks)} checks passed")
		return not failed

	if not _run(context, go):
		raise click.exceptions.Exit(1)


@demo_gen.command("uninstall")
@click.option("--run", "run_name", help="Run to remove (default: the only active run)")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation")
@click.option(
	"--registry-only",
	is_flag=True,
	help="Remove transactions one by one from the registry (tier A) even for a company the run created",
)
@click.option(
	"--no-backup",
	is_flag=True,
	help="Skip the site backup taken before removing demo data from your own company (--use-wizard-company)",
)
@pass_context
def uninstall(context, run_name, yes, registry_only, no_backup):
	"""Remove a run's demo company, its transactions and everything it created."""
	from erpnext_demo_gen import service

	def go():
		from erpnext_demo_gen.registry import active_runs

		target = run_name or ", ".join(f"{r.name} ({r.company})" for r in active_runs()) or "nothing"
		if not yes:
			click.confirm(f"Delete demo data of {target}?", abort=True)
		run = service.uninstall(run_name, log=_log, registry_only=registry_only, no_backup=no_backup)
		_log(f"{run.name} uninstalled{_took(run)}")

	_run(context, go)


# ---------------------------------------------------------------- snapshots
@demo_gen.group("snapshot")
def snapshot():
	"""Build a demo snapshot, or create a new site from one (no site needed)."""


ROOT_PASSWORD = click.option(
	"--db-root-password",
	prompt="MariaDB root password",
	hide_input=True,
	help="Needed to create the site, as for bench new-site",
)
HOST_SCOPE = click.option(
	"--mariadb-user-host-login-scope",
	"host_scope",
	help="As for bench new-site; '%' when MariaDB runs in Docker",
)


def _snapshot_run(fn):
	from erpnext_demo_gen.snapshot import SnapshotError

	try:
		return fn()
	except SnapshotError as e:
		raise click.ClickException(str(e)) from e


@snapshot.command("build")
@click.option("--country", required=True, help=COUNTRY_HELP)
@click.option("--pack", help=PACK_HELP)
@click.option(
	"--size",
	default="medium",
	show_default=True,
	type=click.Choice(SIZES),
)
@click.option("--seed", default=1, show_default=True, type=int)
@click.option("--end-date", help="Last day of generated data (default: today)")
@click.option("--out", "out_dir", help="Folder for the snapshot (default: <bench>/demo-snapshots)")
@ROOT_PASSWORD
@HOST_SCOPE
def snapshot_build(country, pack, size, seed, end_date, out_dir, db_root_password, host_scope):
	"""Build a snapshot on a throwaway site: wizard, install, verify, back up, drop."""
	from erpnext_demo_gen import snapshot as snap
	from erpnext_demo_gen.packs import PackNotFound, find_pack

	try:
		pack_id = find_pack(country, pack)
	except PackNotFound as e:
		raise click.ClickException(str(e)) from e

	def go():
		path = snap.build(pack_id, size, seed, end_date, db_root_password, host_scope, out_dir, log=_log)
		_log(f"Snapshot ready: {path} (and its .json manifest)")

	_snapshot_run(go)


@snapshot.command("new-site")
@click.argument("name")
@click.argument("dump")
@click.option("--admin-password", help="Administrator password for the new site (default: changeme)")
@ROOT_PASSWORD
@HOST_SCOPE
def snapshot_new_site(name, dump, admin_password, db_root_password, host_scope):
	"""Create a new site NAME from a snapshot DUMP (.sql.gz with its .json manifest)."""
	from erpnext_demo_gen import snapshot as snap

	_snapshot_run(lambda: snap.new_site(name, snap.find_file(dump), admin_password, db_root_password, host_scope, log=_log))


commands = [demo_gen]
