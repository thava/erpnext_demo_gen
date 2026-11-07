"""Service layer: install, status, uninstall. The CLI (commands.py) and the desk
"Delete Demo Data" button (api.py) are thin wrappers over these functions (M-13).
"""

import json

import frappe
from frappe.utils import getdate, nowdate

from demo_data.jobs import INLINE_JOBS, inline_jobs
from demo_data.packs import load_pack
from demo_data.registry import RESUMABLE_STATUSES, Run, active_runs


class DemoDataError(Exception):
	"""A refusal or failure with a message meant for the user."""


# ---------------------------------------------------------------- preflight
def preflight(force: bool = False) -> list[str]:
	"""Hard failures raise; soft ones (overridable with force) are returned as warnings."""
	installed = frappe.get_installed_apps()
	for app in ("erpnext", "india_compliance"):
		if app not in installed:
			raise DemoDataError(f"{app} must be installed on the site first")
	if not frappe.is_setup_complete():
		raise DemoDataError("Finish the setup wizard first")
	check_redis()

	problems = []
	from india_compliance.gst_india.utils import is_api_enabled

	if is_api_enabled():
		problems.append(
			"india_compliance's GST API is enabled; generated invoices could reach the GST portal "
			"(e-invoice, e-waybill, GSTIN lookups)"
		)
	demo = {r.company for r in active_runs()}
	other_gl = frappe.db.sql(
		"select company, count(*) from `tabGL Entry` where is_cancelled=0 group by company"
	)
	real = {company: n for company, n in other_gl if company not in demo}
	if real:
		problems.append(
			"the site already has transactions ("
			+ ", ".join(f"{c}: {n} GL entries" for c, n in real.items())
			+ ")"
		)
	if problems and not force:
		raise DemoDataError(
			"Refusing to install: " + "; ".join(problems) + ". Use --force to install anyway."
		)
	return problems


def check_redis():
	"""Transaction Deletion Record needs the Redis queue even in single-transaction mode (F-19)."""
	from frappe.utils.background_jobs import get_redis_conn

	try:
		get_redis_conn().ping()
	except Exception as e:
		raise DemoDataError(
			f"The Redis queue is not reachable ({e}); start it (bench start) and retry"
		) from e


# ---------------------------------------------------------------- install
def resolve_params(
	pack_id, size, seed, end_date, home_state, company, use_wizard_company
) -> tuple[dict, dict]:
	pack = load_pack(pack_id)
	if size not in pack["sizes"]:
		raise DemoDataError(f"Unknown size {size!r}; choose one of {', '.join(pack['sizes'])}")
	params = {
		"pack": pack_id,
		"pack_version": pack["pack_version"],
		"size": size,
		"seed": int(seed),
		"end_date": str(getdate(end_date or nowdate())),
		"months": pack["sizes"][size]["months"],
		"home_state": home_state or pack["company"]["home_state"],
		"company": company,
		"use_wizard_company": bool(use_wizard_company),
	}
	if use_wizard_company:
		wizard = company or frappe.db.get_single_value("Global Defaults", "default_company")
		if not wizard or not frappe.db.exists("Company", wizard):
			raise DemoDataError("--use-wizard-company needs an existing default company (or --company)")
		params["company"] = wizard
	elif company and frappe.db.exists("Company", company):
		raise DemoDataError(
			f"Company {company!r} already exists; pick a new name or use --use-wizard-company"
		)
	from demo_data.india.geo import CITIES

	if params["home_state"] not in CITIES:
		raise DemoDataError(
			f"No curated cities for state {params['home_state']!r}; choose one of: {', '.join(sorted(CITIES))}"
		)
	return pack, params


INPUT_KEYS = ("pack", "size", "seed", "end_date", "home_state", "use_wizard_company")


def find_resumable(params: dict) -> Run | None:
	"""An unfinished run with the same inputs is resumed; any other active run blocks a new install."""
	for row in active_runs():
		old = json.loads(row.params or "{}")
		same = all(old.get(k) == params.get(k) for k in INPUT_KEYS) and (
			not params.get("company") or params["company"] == old.get("company")
		)
		if same and row.status in RESUMABLE_STATUSES:
			return Run(row.name)
		if same and row.status == "Completed":
			run = Run(row.name)
			if run.gaps():
				return run  # completed with failures: re-running retries them
			raise DemoDataError(f"{row.name} with these inputs is already installed ({row.company})")
		raise DemoDataError(
			f"{row.name} ({row.pack}/{row.size}, {row.company}) is {row.status}; uninstall it first"
		)
	return None


def install(
	pack,
	size="small",
	seed=1,
	end_date=None,
	home_state=None,
	company=None,
	use_wizard_company=False,
	force=False,
	log=print,
):
	warnings = preflight(force)
	for w in warnings:
		log(f"Warning (--force): {w}")
	pack_data, params = resolve_params(pack, size, seed, end_date, home_state, company, use_wizard_company)
	run = find_resumable(params)
	if run:
		log(f"Resuming {run.name}")
	else:
		run = Run.create(params)
		log(f"Started {run.name}")
	run.set_status("Running", error="")

	from demo_data.setup.company import setup_company

	frappe.flags.mute_emails = True
	try:
		with inline_jobs() as jobs:
			company_name = setup_company(run, pack_data)
			log(f"Company: {company_name}")
			stats = write_plan(run, pack_data, log)
			process_reposts(run.doc.company, log)
		queued = {k: n for k, n in jobs.items() if k not in INLINE_JOBS}
		if queued:
			log(f"Background jobs queued: {queued}")
	except Exception as e:
		frappe.db.rollback()
		run.set_status("Failed", error=frappe.get_traceback())
		raise DemoDataError(f"{run.name} failed: {e}. Re-run the same command to resume.") from e

	run.set_status("Completed", counts=json.dumps(run.counts(), indent=1))
	if stats["failed"] or stats["skipped"]:
		log(f"{stats['failed']} failed and {stats['skipped']} skipped; errors are in Demo Data Record")
	return run


def process_reposts(company: str, log=print):
	"""Run the company's queued stock reposts now, so ledgers are final before verify.

	An in-order install queues none (A-9); a resume after failures writes some
	documents behind later ones, and ERPNext queues revaluation for those.
	"""
	from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import execute_reposting_entry

	names = frappe.get_all(
		"Repost Item Valuation",
		filters={"company": company, "status": ["in", ("Queued", "In Progress")], "docstatus": 1},
		order_by="posting_date asc, posting_time asc, creation asc",
		pluck="name",
	)
	if not names:
		return
	log(f"Processing {len(names)} queued stock reposts")
	for name in names:
		execute_reposting_entry(name)
		frappe.db.commit()


def plan_for(run: Run, pack: dict) -> list:
	from demo_data.planner import PlanContext, make_plan
	from demo_data.setup.company import date_range

	start, end = date_range(getdate(run.params.end_date), run.params.months)
	ctx = PlanContext(pack, run.params.size, run.params.seed, run.params.home_state, start, end)
	return make_plan(ctx)


def write_plan(run: Run, pack: dict, log=print) -> dict:
	from demo_data.writers import ApiWriter, WriteContext

	plan = plan_for(run, pack)
	log(f"Plan: {len(plan)} documents")
	wctx = WriteContext.for_run(run, pack, plan_start(run))
	stats = ApiWriter(run, wctx, log=log).execute(plan)
	log(
		f"Wrote {stats['created']} new, reused {stats['reused']}, {stats['already']} already present, "
		f"{stats['failed']} failed, {stats['skipped']} skipped in {stats['seconds']}s"
	)
	return stats


def plan_start(run: Run):
	from demo_data.setup.company import date_range

	return date_range(getdate(run.params.end_date), run.params.months)[0]


# ---------------------------------------------------------------- status
def status() -> list[dict]:
	runs = frappe.get_all(
		"Demo Data Run",
		fields=["name", "status", "pack", "size", "seed", "end_date", "company", "started_at", "finished_at"],
		order_by="creation desc",
	)
	for r in runs:
		r["counts"] = Run(r.name).counts()
	return runs


# ---------------------------------------------------------------- uninstall
def uninstall(run_name: str | None = None, log=print) -> Run:
	from demo_data.uninstall import uninstall_run

	if not run_name:
		runs = active_runs()
		if not runs:
			raise DemoDataError("No demo data is installed")
		if len(runs) > 1:
			raise DemoDataError("Several runs are active; pass --run: " + ", ".join(r.name for r in runs))
		run_name = runs[0].name
	run = Run(run_name)
	if run.doc.status == "Uninstalled":
		raise DemoDataError(f"{run.name} is already uninstalled")
	uninstall_run(run, log=log)
	return run


# ---------------------------------------------------------------- verify
def verify(run_name: str | None = None):
	from demo_data.verify import verify_run

	if not run_name:
		runs = [r for r in active_runs() if r.status == "Completed"]
		if not runs:
			raise DemoDataError("No completed demo run to verify")
		run_name = runs[-1].name
	run = Run(run_name)
	return run, verify_run(run)
