"""Desk entry points (the DemoGen page, design 5.19). System Managers only.

Thin wrappers over erpnext_demo_gen.service, like the CLI (M-13): the page validates an
install the way the CLI does, then a long-queue job (jobs.py) runs it.
"""

import frappe
from frappe import _

from erpnext_demo_gen import jobs
from erpnext_demo_gen.registry import DONE_STATES, Run

PAGE_SIZES = ("small", "medium")  # large and snapshots stay CLI-only (DEC-33)
SIZE_NOTES = {"small": (300, "1 min"), "medium": (1200, "5 min")}  # documents, time (README "Sizes")
STALE_STATUSES = ("Running", "Uninstalling", "Planned")
# country -> (the tax, the company's tax ID), for the registration option and the run card
TAX_NAMES = {"IN": ("GST", "GSTIN"), "AE": ("VAT", "TRN"), "DE": ("VAT", "USt-IdNr."), "US": ("sales tax", "EIN")}


def has_app_permission() -> bool:
	"""Apps screen: the DemoGen entry is for System Managers."""
	return "System Manager" in frappe.get_roles()


def _check():
	frappe.only_for("System Manager")


# ---------------------------------------------------------------- reading
@frappe.whitelist()
def get_state() -> dict:
	"""Everything the page shows: active runs, the job and its progress, workers, history."""
	_check()
	from erpnext_demo_gen import service
	from erpnext_demo_gen.packs import describe

	live, job = jobs.get_live(), jobs.job_status()
	active = jobs.job_active()
	if live.get("status") in ("queued", "running") and not active:
		live["status"] = "stopped"  # the worker died, timed out or was restarted
	runs = []
	for r in service.status()["active"]:
		params = Run(r.name).params
		totals = r.totals or {}
		r.update(
			pack_label=describe(r.pack),
			country=params.get("country"),
			country_name=_country_name(params.get("country")),
			months=params.get("months"),
			home_state=params.get("home_state"),
			wizard=bool(params.get("use_wizard_company")),
			registration=params.get("registration", "registered"),
			tax_id=_tax_id(params.get("country"), r.company),
			tax_id_name=TAX_NAMES.get(params.get("country") or "", ("tax", "Tax ID"))[1],
			documents=sum(totals.get(s, 0) for s in (*DONE_STATES, "Reused")),
			failed=sum(totals.get(s, 0) for s in ("Failed", "Skipped")),
			company_exists=bool(r.company and frappe.db.exists("Company", r.company)),
			# a run left Running or Uninstalling without a job was stopped (Ctrl+C, a worker restart)
			stopped=r.status in STALE_STATUSES and not active,
		)
		runs.append(r)
	history = frappe.get_all(
		"Demo Data Run",
		fields=["name", "status", "pack", "size", "seed", "company", "started_at", "finished_at", "modified"],
		order_by="creation desc",
		limit=10,
	)
	for h in history:
		h["pack_label"] = describe(h.pack)
	return {
		"runs": runs,
		"job": {"status": job, "active": active, **live},
		"workers": jobs.long_queue_workers(),
		"history": history,
		"default_company": frappe.db.get_single_value("Global Defaults", "default_company"),
	}


@frappe.whitelist()
def get_install_options() -> dict:
	"""Countries, their packs, sizes and home states for the install form."""
	_check()
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen import service
	from erpnext_demo_gen.packs import default_packs, list_packs, load_pack


	countries = {}
	defaults = default_packs()
	installed = set(frappe.get_installed_apps())
	site_company = frappe.db.get_single_value("Global Defaults", "default_company")
	site_country = site_company and frappe.get_cached_value("Company", site_company, "country")
	for p in list_packs():
		locale = get_locale(p["country"])
		c = countries.setdefault(
			p["country"],
			{
				"code": p["country"],
				"name": locale.country,
				"currency": locale.currency,
				"default_pack": defaults.get(p["country"]),
				"missing_apps": [a for a in locale.required_apps if a not in installed],
				"site_problem": service.site_problem(locale, installed),
				"tax": TAX_NAMES.get(p["country"], ("tax", "tax ID"))[0],
				"tax_id_name": TAX_NAMES.get(p["country"], ("tax", "tax ID"))[1],
				"registration_label": _("Registered for Texas sales tax")
				if p["country"] == "US"
				else _("Registered for {0} (made-up {1})").format(*TAX_NAMES.get(p["country"], ("tax", "tax ID"))),
				"unregistered": _unregistered_option(locale),
				"is_site_country": locale.country == site_country,
				"packs": [],
				"home_states": locale.home_regions(),
			},
		)
		pack = load_pack(p["id"])
		c["packs"].append(
			{
				"name": p["pack"],
				"title": p["title"],
				"home_state": pack["company"]["home_state"],
				"sizes": [
					{
						"size": s,
						"months": pack["sizes"][s]["months"],
						"documents": SIZE_NOTES[s][0],
						"time": SIZE_NOTES[s][1],
					}
					for s in PAGE_SIZES
					if s in pack["sizes"]
				],
			}
		)
	order = ["IN", "US", "AE", "DE"]
	return {"countries": sorted(countries.values(), key=lambda c: order.index(c["code"]) if c["code"] in order else 99)}


def _unregistered_option(locale) -> dict:
	"""Whether the page offers "not registered" for the country, and why not."""
	from erpnext_demo_gen.service import DemoDataError

	try:
		locale.check_options(True)
		return {"offered": True, "warning": locale.unregistered_warning}
	except DemoDataError as e:
		return {"offered": False, "reason": str(e)}


def _tax_id(country: str | None, company: str | None) -> str | None:
	"""The demo company's (made-up) tax ID: India's GSTIN, otherwise the Company's Tax ID."""
	if not (company and frappe.db.exists("Company", company)):
		return None
	if country == "IN":
		gstin = frappe.db.get_value("Company", company, "gstin")
		if gstin:
			return gstin
		addresses = frappe.get_all("Dynamic Link", {"link_doctype": "Company", "link_name": company, "parenttype": "Address"}, pluck="parent")
		return addresses and frappe.db.get_value(
			"Address", {"name": ["in", addresses], "is_your_company_address": 1, "gstin": ["is", "set"]}, "gstin"
		) or None
	return frappe.db.get_value("Company", company, "tax_id") or None


def _country_name(code: str | None) -> str | None:
	from erpnext_demo_gen.locales import get_locale

	try:
		return get_locale(code).country if code else None
	except Exception:
		return code


# ---------------------------------------------------------------- actions
@frappe.whitelist(methods=["POST"])
def start_install(
	country: str,
	pack: str | None = None,
	size: str = "small",
	seed: int = 1,
	end_date: str | None = None,
	home_state: str | None = None,
	company_name: str | None = None,
	unregistered: int = 0,
	force: int = 0,
) -> dict:
	"""Check the install as the CLI would, then queue it. A refusal the user may override
	comes back as {"confirm": reason, "question": ...}; the page asks, then calls again with
	force=1 (the CLI's --force)."""
	_check()
	if size not in PAGE_SIZES:
		frappe.throw(_("The page installs small or medium demos; use the CLI for {0}").format(size))
	options = dict(
		country=country,
		pack=pack or None,
		size=size,
		seed=int(seed or 1),
		end_date=end_date or None,
		home_state=home_state or None,
		company=(company_name or "").strip() or None,
		unregistered=bool(int(unregistered or 0)),
		force=bool(int(force or 0)),
	)
	confirm = _dry_run(options)
	if confirm:
		return confirm
	jobs.enqueue("install", "erpnext_demo_gen.jobs.install_job", **options)
	return {"queued": True}


@frappe.whitelist(methods=["POST"])
def resume_install(run: str) -> dict:
	"""Re-run a stopped or failed install with the run's own inputs; it resumes (as the CLI)."""
	_check()
	if not frappe.db.exists("Demo Data Run", run):
		frappe.throw(_("No demo run {0}").format(run))
	params = Run(run).params
	options = dict(
		country=params.get("country") or "IN",
		pack=params.get("pack_name"),
		size=params.get("size"),
		seed=params.get("seed"),
		end_date=params.get("end_date"),
		home_state=params.get("home_state"),
		company=None if params.get("use_wizard_company") else params.get("company"),
		use_wizard_company=bool(params.get("use_wizard_company")),
		unregistered=params.get("registration") == "unregistered",
		force=True,  # confirmed when the install was first started
	)
	jobs.enqueue("install", "erpnext_demo_gen.jobs.install_job", live_run=run, **options)
	return {"queued": True}


@frappe.whitelist(methods=["POST"])
def start_uninstall(run: str, confirm_company: str) -> dict:
	"""Queue the removal of a run. The user types the company name to confirm."""
	_check()
	company = frappe.db.get_value("Demo Data Run", run, "company")
	if not company:
		frappe.throw(_("No demo run {0}").format(run))
	if (confirm_company or "").strip() != company:
		frappe.throw(_("Type the company name {0} exactly to confirm").format(frappe.bold(company)))
	jobs.enqueue("uninstall", "erpnext_demo_gen.jobs.uninstall_job", live_run=run, run_name=run)
	return {"queued": True}


@frappe.whitelist(methods=["POST"])
def verify(run: str | None = None) -> dict:
	"""Run verify in the request (a few seconds at medium size)."""
	_check()
	from erpnext_demo_gen import service

	try:
		r, checks = service.verify(run)
	except service.DemoDataError as e:
		frappe.throw(str(e))
	return {
		"run": r.name,
		"checks": [{"name": c.name, "ok": bool(c.ok), "detail": c.detail} for c in checks],
	}


def _dry_run(options: dict) -> dict | None:
	"""The CLI's checks without writing anything; None when the install can be queued.

	Every refusal the user may override (the CLI's --force) is collected, so the page asks
	once about all of them: e.g. a site in use and the unregistered turnover warning.
	"""
	from erpnext_demo_gen import service
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import PackNotFound, find_pack, load_pack

	reasons, questions = [], []

	def ask(check):
		try:
			return check()
		except service.NeedsForce as e:
			reasons.append(e.reason)
			questions.append(e.question)

	try:
		try:
			pack_id = find_pack(options["country"], options["pack"])
		except PackNotFound as e:
			raise service.DemoDataError(str(e)) from e
		locale = get_locale(load_pack(pack_id))
		ask(lambda: service.preflight(False, locale))
		_pack, params = service.resolve_params(
			pack_id,
			options["size"],
			options["seed"],
			options["end_date"],
			options["home_state"],
			options["company"],
			False,
			options["unregistered"],
		)
		ask(lambda: service.site_in_use(params, False, log=lambda *_: None))
		service.find_resumable(params)
		if options["unregistered"]:
			reasons.append(f"Not registered: {locale.unregistered_warning}.")
			questions.append(_("Install it unregistered anyway?"))
	except service.DemoDataError as e:
		frappe.throw(str(e), title=_("Cannot install"))
	if not reasons or options["force"]:  # force: the user has confirmed these
		return None
	return {"confirm": "\n\n".join(reasons), "question": questions[-1] if len(questions) == 1 else _("Install anyway?")}


# ---------------------------------------------------------------- setup wizard
def after_setup_wizard(args=None):
	"""Tell whoever finished the setup wizard where DemoGen is (design 5.19 step 3)."""
	try:
		user = frappe.session.user
		if not user or user == "Guest":
			return
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": _("DemoGen is installed: add demo data from the apps screen"),
				"email_content": _(
					"DemoGen, an extended demo data generator for ERPNext, can add a demo company "
					"with a few months of realistic transactions, and remove it again."
				),
				"link": "/desk/demo-gen",
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error("DemoGen: note after the setup wizard")  # never break the wizard
