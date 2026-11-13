"""Service layer: install, status, uninstall. The CLI (commands.py) and the desk
page (api.py) are thin wrappers over these functions (M-13).
"""

import json

import frappe
from frappe.utils import getdate, nowdate

from erpnext_demo_gen.jobs import INLINE_JOBS, inline_jobs
from erpnext_demo_gen.packs import describe, load_pack
from erpnext_demo_gen.registry import RESUMABLE_STATUSES, Run, active_runs

# Transactions in the user's own company are removed by tier A (registry-based) uninstall.
WIZARD_COMPANY_SUPPORTED = True


class DemoDataError(Exception):
	"""A refusal or failure with a message meant for the user."""


class NeedsForce(DemoDataError):
	"""A refusal the user may override (CLI: --force; desk page: a confirmation).

	str() is the CLI message (reason, then the "--force" advice); the page shows the
	reason and asks question.
	"""

	def __init__(self, reason: str, advice: str = "Use --force to install anyway.", question: str = "Install anyway?"):
		self.reason, self.question = reason, question
		super().__init__(f"{reason}{chr(10) if chr(10) in reason else ' '}{advice}")


# ---------------------------------------------------------------- preflight
def preflight(force: bool = False, locale=None) -> list[str]:
	"""Hard failures raise; soft ones (overridable with force) are returned as warnings."""
	from erpnext_demo_gen.locales import get_locale

	locale = locale or get_locale()
	installed = frappe.get_installed_apps()
	for app in locale.required_apps:
		if app not in installed:
			raise DemoDataError(f"{app} must be installed on the site first")
	if not frappe.is_setup_complete():
		raise DemoDataError("Finish the setup wizard first")
	check_redis()

	problems = locale.preflight_problems()
	if problems and not force:
		raise NeedsForce("Refusing to install: " + "; ".join(problems) + ".")
	return problems


def existing_transactions(only_company: str | None = None) -> list[str]:
	"""One line per company that already has ledger entries outside any active demo run."""
	demo = {r.company for r in active_runs()}
	default = frappe.db.get_single_value("Global Defaults", "default_company")
	lines = []
	for company, documents, entries in frappe.db.sql(
		"""select company, count(distinct voucher_type, voucher_no), count(*)
		from `tabGL Entry` where is_cancelled=0 group by company"""
	):
		if company in demo or (only_company and company != only_company):
			continue
		role = " (default company)" if company == default else ""
		noun = "document" if documents == 1 else "documents"
		lines.append(f"{company}{role}: {documents} {noun}, {entries} GL entries")
	return lines


def site_in_use(params: dict, force: bool, log=print):
	"""Existing transactions need --force. Say plainly what installing would do to them.

	In wizard mode only the target company counts: the demo writes nowhere else and
	leaves the default company as it is, so an unused wizard company needs no --force.
	"""
	lines = existing_transactions(params["company"] if params["use_wizard_company"] else None)
	if not lines:
		return
	listing = "\n".join(f"  {line}" for line in lines)
	if params["use_wizard_company"]:
		effect = (
			f"--use-wizard-company adds the demo's documents to {params['company']},\n"
			"next to its existing ones. Uninstall removes only the demo's documents; yours stay."
		)
		ask = "Installing into a company that is in use needs --force."
		confirm = "Install into a company that is in use?"
	else:
		effect = (
			"The demo goes into a new, separate company (a peer, not a child company) and\n"
			"does not change these. It becomes the default company while installed;\n"
			"uninstall deletes it and restores the current default."
		)
		ask = "This is safe, but because the site is in use, installing needs --force."
		confirm = "This is safe. Install anyway?"
	if not force:
		raise NeedsForce(f"This site already has transactions:\n{listing}\n{effect}", ask, confirm)
	log(f"Note (--force): this site already has transactions:\n{listing}\n{effect}")


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
	pack_id, size, seed, end_date, home_state, company, use_wizard_company, unregistered=False
) -> tuple[dict, dict]:
	from erpnext_demo_gen.locales import get_locale

	pack = load_pack(pack_id)
	locale = get_locale(pack)
	choices = locale.region_choices()
	if home_state:
		given, home_state = home_state, locale.resolve_region(home_state)
		if not home_state:
			raise DemoDataError(f"Unknown state {given!r}; use a name or code: {choices}")
	locale.check_options(unregistered)
	if size not in pack["sizes"]:
		raise DemoDataError(f"Unknown size {size!r}; choose one of {', '.join(pack['sizes'])}")
	params = {
		"pack": pack_id,
		"pack_name": pack.get("pack") or pack_id,
		"country": locale.code,
		"pack_version": pack["pack_version"],
		"size": size,
		"seed": int(seed),
		"end_date": str(getdate(end_date or nowdate())),
		"months": pack["sizes"][size]["months"],
		"home_state": home_state or pack["company"]["home_state"],
		"company": company,
		"use_wizard_company": bool(use_wizard_company),
		"registration": "unregistered" if unregistered else "registered",
		"fictitious_gstin": False,  # India wizard mode: set by check_wizard_company
	}
	if use_wizard_company and not WIZARD_COMPANY_SUPPORTED:
		raise DemoDataError(
			"--use-wizard-company is not available yet: removing demo transactions from your own "
			"company needs registry-based (tier A) uninstall. Install into a separate demo company instead."
		)
	if use_wizard_company:
		if company:
			raise DemoDataError(
				"--demo-company-name names a new demo company; it cannot be used with --use-wizard-company"
			)
		wizard = frappe.db.get_single_value("Global Defaults", "default_company")
		if not wizard or not frappe.db.exists("Company", wizard):
			raise DemoDataError("--use-wizard-company needs an existing default company")
		country, currency = frappe.db.get_value("Company", wizard, ["country", "default_currency"])
		if country != locale.country or currency != locale.currency:
			raise DemoDataError(
				f"The {pack_id} pack is for {locale.country} ({locale.currency}), and {wizard!r} is set "
				f"up for {country or 'no country'} ({currency or 'no currency'}). Its customers, "
				f"addresses, tax setup and {locale.currency} prices would not fit."
			)
		params["company"] = wizard
		locale.check_wizard_company(wizard, params, home_state, unregistered)
	elif company and frappe.db.exists("Company", company):
		raise DemoDataError(
			f"Company {company!r} already exists; pick another --demo-company-name or use --use-wizard-company"
		)
	from erpnext_demo_gen.setup.company import fiscal_year_conflict

	conflict = fiscal_year_conflict(locale, getdate(params["end_date"]), params["months"])
	if conflict:
		raise DemoDataError(conflict)
	if params["home_state"] not in locale.home_regions():
		raise DemoDataError(f"No curated cities for {params['home_state']} yet; choose one of: {choices}")
	return pack, params


INPUT_KEYS = ("pack", "size", "seed", "end_date", "home_state", "use_wizard_company", "registration", "fictitious_gstin")


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
			f"{row.name} ({describe(row.pack)}/{row.size}, {row.company}) is {row.status}; uninstall it first"
		)
	return None


def install(
	pack=None,
	size="medium",
	seed=1,
	end_date=None,
	home_state=None,
	company=None,
	use_wizard_company=False,
	force=False,
	log=print,
	unregistered=False,
	country=None,
):
	"""Install a pack for a country. The country is required and explicit; the pack is
	optional (the country's default pack)."""
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import PackNotFound, default_packs, find_pack, list_packs

	if not country:
		raise DemoDataError("Choose the country explicitly: --country IN (India) or --country US (United States)")
	try:
		pack_id = find_pack(country, pack)
	except PackNotFound as e:
		raise DemoDataError(str(e)) from e
	info = next(p for p in list_packs() if p["id"] == pack_id)
	locale = get_locale(load_pack(pack_id))
	default = " (its default pack)" if not pack and default_packs().get(info["country"]) == info["pack"] else ""
	log(f"Pack: {info['pack']}{default}, country: {locale.country} ({locale.code}), currency {locale.currency}")
	site_company = frappe.db.get_single_value("Global Defaults", "default_company")
	site_currency = site_company and frappe.get_cached_value("Company", site_company, "default_currency")
	if site_currency and site_currency != locale.currency and not use_wizard_company:
		log(
			f"Note: this site's default company {site_company!r} uses {site_currency}; the demo creates its own "
			f"{locale.country} company in {locale.currency} next to it"
		)
	pack = pack_id
	warnings = preflight(force, locale)
	pack_data, params = resolve_params(
		pack, size, seed, end_date, home_state, company, use_wizard_company, unregistered
	)
	site_in_use(params, force, log)
	if params["registration"] == "unregistered":
		if not force:
			raise NeedsForce(f"Refusing to install: {locale.unregistered_warning}.")
		warnings.append(locale.unregistered_warning)
	if params["fictitious_gstin"]:
		log(
			f"Note: adding a company address with a made-up GSTIN to {params['company']} (state "
			f"{params['home_state']}); it is fictitious, for the demo only, and removed on uninstall"
		)
	for w in warnings:
		log(f"Warning (--force): {w}")
	run = find_resumable(params)
	if run:
		log(f"Resuming {run.name}")
	else:
		run = Run.create(params)
		log(f"Started {run.name}")
	run.set_status("Running", error="")

	from erpnext_demo_gen.setup.company import setup_company

	frappe.flags.mute_emails = True
	try:
		with inline_jobs() as jobs:
			log("Setting up the company, warehouses, fiscal years and bank accounts...")
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

	run.set_status("Completed", counts=json.dumps(run.counts(), indent=1), totals=True)
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
	from erpnext_demo_gen.planner import PlanContext, make_plan
	from erpnext_demo_gen.setup.company import date_range

	start, end = date_range(getdate(run.params.end_date), run.params.months)
	ctx = PlanContext(pack, run.params.size, run.params.seed, run.params.home_state, start, end)
	ctx.sales_tax = run.params.get("registration", "registered") == "registered"
	return make_plan(ctx)


def write_plan(run: Run, pack: dict, log=print) -> dict:
	from erpnext_demo_gen.writers import ApiWriter, WriteContext

	from erpnext_demo_gen.progress import duration, install_seconds

	plan = plan_for(run, pack)
	todo = len(plan) - len(set(run.done_map()) & {pd.key for pd in plan})
	log(f"Plan: {len(plan)} documents" + (f", {todo} still to write" if todo < len(plan) else ""))
	if todo:
		log(
			f"Writing them takes about {duration(install_seconds(todo))}; please wait. Progress is shown "
			"every 20 s. If stopped (Ctrl+C), the same command resumes where it left off."
		)
	wctx = WriteContext.for_run(run, pack, plan_start(run))
	stats = ApiWriter(run, wctx, log=log).execute(plan)
	if stats["transient"]:
		# A database conflict outlasted the writer's retries (F-34). One more pass, as a
		# resume would, often writes those steps and the ones depending on them. It cannot
		# help a step whose order mattered (e.g. a partial delivery already shipped by a
		# later one); such a step stays failed and is reported. Other failures would only
		# repeat, so they are not retried.
		log(f"Retrying {stats['failed']} failed step(s) and {stats['skipped']} skipped after them, once")
		again = ApiWriter(run, wctx, log=log).execute(plan)
		stats.update(failed=again["failed"], skipped=again["skipped"], created=stats["created"] + again["created"])
	log(
		f"Wrote {stats['created']} new, reused {stats['reused']}, {stats['already']} already present, "
		f"{stats['failed']} failed, {stats['skipped']} skipped in {stats['seconds']}s"
	)
	return stats


def plan_start(run: Run):
	from erpnext_demo_gen.setup.company import date_range

	return date_range(getdate(run.params.end_date), run.params.months)[0]


# ---------------------------------------------------------------- status
RUN_FIELDS = ["name", "status", "pack", "size", "seed", "end_date", "company", "started_at", "finished_at"]


def status() -> dict:
	"""A short summary: the active runs, totals for the site, and the latest run."""
	runs = frappe.get_all("Demo Data Run", fields=RUN_FIELDS, order_by="creation desc")
	by_status: dict = {}
	for r in runs:
		by_status[r.status] = by_status.get(r.status, 0) + 1
	active = [r for r in runs if r.status != "Uninstalled"]
	for r in active:
		r["totals"] = Run(r.name).totals()
	return {"runs": len(runs), "by_status": by_status, "active": active, "latest": runs[0] if runs else None}


def history(run_name: str | None = None) -> list[dict]:
	"""Runs with their install and uninstall events; the CLI merges them into one timeline.

	With run_name, that run only, plus per doctype what the install created
	(installed) and where each record stands now (current).
	"""
	filters = {"name": run_name} if run_name else {}
	runs = frappe.get_all("Demo Data Run", filters=filters, fields=[*RUN_FIELDS, "params"], order_by="creation")
	if run_name and not runs:
		raise DemoDataError(f"No demo run {run_name!r}")
	for r in runs:
		run = Run(r.name)
		r["months"] = frappe.parse_json(r.params or "{}").get("months")
		r["events"] = run.events() or legacy_events(r)
		if run_name:
			r["installed"] = frappe.parse_json(run.doc.counts or "{}")
			r["current"] = run.counts()
	return runs


def legacy_events(r) -> list[dict]:
	"""Runs from before events were recorded: rebuild what the timestamps show."""
	events = []
	if r.started_at:
		events.append({"at": str(r.started_at), "status": "Running"})
	if r.finished_at:
		events.append({"at": str(r.finished_at), "status": r.status})
	return events


# ---------------------------------------------------------------- uninstall
def uninstall(
	run_name: str | None = None, log=print, registry_only: bool = False, no_backup: bool = False
) -> Run:
	from erpnext_demo_gen.uninstall import uninstall_run

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
	uninstall_run(run, log=log, registry_only=registry_only, no_backup=no_backup)
	return run


# ---------------------------------------------------------------- verify
def verify(run_name: str | None = None):
	from erpnext_demo_gen.verify import verify_run

	if not run_name:
		runs = [r for r in active_runs() if r.status == "Completed"]
		if not runs:
			raise DemoDataError("No completed demo run to verify")
		run_name = runs[-1].name
	run = Run(run_name)
	return run, verify_run(run)
