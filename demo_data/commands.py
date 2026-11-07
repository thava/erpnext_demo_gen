"""bench --site <site> demo-data ...

    demo-data list-packs
    demo-data install --pack furniture_store [--size small] [--seed N] [--end-date YYYY-MM-DD]
                      [--home-state "Tamil Nadu"] [--company NAME] [--use-wizard-company] [--force]
    demo-data status
    demo-data verify [--run DD-RUN-00001]
    demo-data uninstall [--run DD-RUN-00001]

Thin wrappers over demo_data.service (M-13).
"""

import json

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
	"""Install, check and remove realistic India demo data."""


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
@click.option("--home-state", help="State of the demo company (default: the pack's, usually Tamil Nadu)")
@click.option("--company", help="Name for the new demo company (default: generated from the seed)")
@click.option(
	"--use-wizard-company",
	is_flag=True,
	help="Generate into the existing default company instead of a new one",
)
@click.option(
	"--force", is_flag=True, help="Install even if the site already has transactions or the GST API is on"
)
@pass_context
def install(context, pack, size, seed, end_date, home_state, company, use_wizard_company, force):
	"""Install demo data. Re-running the same command resumes an interrupted install."""
	from demo_data import service

	def go():
		run = service.install(
			pack, size, seed, end_date, home_state, company, use_wizard_company, force, log=click.echo
		)
		click.echo(f"{run.name} completed: {json.dumps(run.counts())}")

	_run(context, go)


@demo_data.command("status")
@pass_context
def status(context):
	"""List demo runs and what each created."""
	from demo_data import service

	def go():
		runs = service.status()
		if not runs:
			click.echo("No demo data runs on this site")
		for r in runs:
			click.echo(
				f"{r.name}  {r.status:<12} {r.pack}/{r.size} seed={r.seed} end={r.end_date}  {r.company or ''}"
			)
			for doctype, states in sorted(r["counts"].items()):
				click.echo(f"    {doctype:<28} " + ", ".join(f"{s}: {n}" for s, n in sorted(states.items())))

	_run(context, go)


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
@pass_context
def uninstall(context, run_name, yes):
	"""Remove a run's demo company, its transactions and everything it created."""
	from demo_data import service

	def go():
		from demo_data.registry import active_runs

		target = run_name or ", ".join(f"{r.name} ({r.company})" for r in active_runs()) or "nothing"
		if not yes:
			click.confirm(f"Delete demo data of {target}?", abort=True)
		run = service.uninstall(run_name, log=click.echo)
		click.echo(f"{run.name} uninstalled")

	_run(context, go)


commands = [demo_data]
