"""bench --site <site> demo-data ...

    demo-data list-packs
    demo-data install --pack furniture_store [--size small] [--seed N] [--end-date YYYY-MM-DD]
                      [--home-state TN] [--demo-company-name NAME] [--use-wizard-company]
                      [--no-gst | --fictitious-gstin] [--force]
    demo-data status
    demo-data history [--run DD-RUN-00001] [--limit 10]
    demo-data verify [--run DD-RUN-00001]
    demo-data uninstall [--run DD-RUN-00001] [--registry-only]

Thin wrappers over demo_data.service (M-13).
"""

import click
from frappe.commands import get_site, pass_context


def _connect(context):
	import frappe

	site = get_site(context)
	frappe.init(site=site)
	frappe.connect()
	frappe.flags.mute_emails = True
	return site


def _run(context, fn):
	import frappe

	from demo_data.packs import PackError
	from demo_data.service import DemoDataError

	_connect(context)
	try:
		return fn()
	except (DemoDataError, PackError) as e:
		raise click.ClickException(str(e)) from e
	finally:
		frappe.destroy()


@click.group("demo-data")
def demo_data():
	"""Install, check and remove realistic demo data for ERPNext. India only.

	The demo is an Indian business: INR prices, Indian customers and suppliers
	with GSTINs, and GST through india_compliance (which must be installed).
	--use-wizard-company needs the default company to be Indian (INR).

	For a business not registered for GST, use install --no-gst --force.
	"""


@demo_data.command("list-packs")
def list_packs():
	from demo_data.packs import list_packs as _list

	for p in _list():
		click.echo(f"{p['id']:<24} v{p['pack_version']}  {p['title']}")


@demo_data.command("install")
@click.option("--pack", required=True, help="Pack id (see list-packs)")
@click.option("--size", default="small", show_default=True, type=click.Choice(["small", "medium"]))
@click.option("--seed", default=1, show_default=True, type=int, help="Same seed, same data")
@click.option("--end-date", help="Last day of generated data (default: today)")
@click.option("--home-state", help="State of the demo company: name, code (TN, KA) or GST state code (33). Default: the pack's, usually TN")
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
	"--no-gst",
	is_flag=True,
	help="Unregistered company: no GST on sales, purchase GST in cost. Needs --force (turnover is above the threshold)",
)
@click.option(
	"--fictitious-gstin",
	is_flag=True,
	help="Wizard company without a GSTIN: add a company address with a made-up GSTIN (removed on uninstall)",
)
@click.option(
	"--force",
	is_flag=True,
	help="Needed when: the site already has transactions; the GST API is on; or --no-gst is used",
)
@click.option("--verbose", is_flag=True, help="At the end, list what was created per doctype")
@pass_context
def install(
	context,
	pack,
	size,
	seed,
	end_date,
	home_state,
	demo_company_name,
	use_wizard_company,
	no_gst,
	fictitious_gstin,
	force,
	verbose,
):
	"""Install demo data. Re-running the same command resumes an interrupted install."""
	from demo_data import service

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
			no_gst=no_gst,
			fictitious_gstin=fictitious_gstin,
		)
		_log(f"{run.name} completed: {_documents(run.totals())} in {run.doc.company}{_took(run)}")
		if verbose:
			_counts_table(run.counts())
		click.echo("Check it with: demo-data verify. Remove it with: demo-data uninstall.")

	_run(context, go)


@demo_data.command("status")
@pass_context
def status(context):
	"""What is installed now, in short. See history for past runs."""
	from demo_data import service

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
		click.echo(f"Runs on this site: {s['runs']} ({parts}). Details: demo-data history")

	_run(context, go)


@demo_data.command("history")
@click.option("--run", "run_name", help="Only this run, plus what it created per doctype")
@click.option("--limit", default=20, show_default=True, help="Number of events to show")
@pass_context
def history(context, run_name, limit):
	"""Install and uninstall events of all runs, newest first."""
	from demo_data import service

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
	return f"{r.pack}/{r.size} seed {r.seed}, {months} up to {r.end_date}, company {r.company or '-'}"


def _describe(r) -> str:
	return f"{r.pack}/{r.size} seed {r.seed}, data up to {r.end_date}, company {r.company or '-'}"


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
	from demo_data.progress import duration

	return duration(seconds)


def _log(message: str):
	"""Echo with a timestamp, so each step shows when it happened."""
	from frappe.utils import now_datetime

	click.echo(f"{now_datetime():%Y-%m-%d %H:%M:%S}  {message}")


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


@demo_data.command("verify")
@click.option("--run", "run_name", help="Run to check (default: the latest completed run)")
@pass_context
def verify(context, run_name):
	"""Check ledgers, aging, stock, registry and screen coverage. Exits 1 if any check fails."""
	from demo_data import service

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


@demo_data.command("uninstall")
@click.option("--run", "run_name", help="Run to remove (default: the only active run)")
@click.option("--yes", is_flag=True, help="Do not ask for confirmation")
@click.option(
	"--registry-only",
	is_flag=True,
	help="Remove transactions one by one from the registry (tier A) even for a company the run created",
)
@pass_context
def uninstall(context, run_name, yes, registry_only):
	"""Remove a run's demo company, its transactions and everything it created."""
	from demo_data import service

	def go():
		from demo_data.registry import active_runs

		target = run_name or ", ".join(f"{r.name} ({r.company})" for r in active_runs()) or "nothing"
		if not yes:
			click.confirm(f"Delete demo data of {target}?", abort=True)
		run = service.uninstall(run_name, log=_log, registry_only=registry_only)
		_log(f"{run.name} uninstalled{_took(run)}")

	_run(context, go)


commands = [demo_data]
