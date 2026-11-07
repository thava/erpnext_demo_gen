"""Uninstall a demo run (M-9, design 5.9).

Order, as established by the Phase 0 spike (section 6.2):
1. Restore the previous default company and clear Global Defaults.demo_company
   (Company.on_trash refuses to delete the registered demo company).
2. Tier B: Transaction Deletion Record for the demo company, in-process. Skipped
   when the demo was generated into the wizard company: that company holds the
   user's own data.
3. Walk the registry in reverse creation order and delete what remains. A record
   that is still linked from non-demo data is skipped and reported, not forced.
   The company comes last because it was created first.
"""

import json

import frappe
from frappe.exceptions import LinkExistsError

from demo_data.jobs import inline_jobs
from demo_data.registry import Run
from demo_data.setup.tax_templates import delete_template_rows

LEDGERS = ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry")


def uninstall_run(run: Run, log=print):
	from demo_data.service import DemoDataError, check_redis

	company = run.doc.company
	own_company = not run.params.get("use_wizard_company")
	run.set_status("Uninstalling", error="")
	try:
		with inline_jobs():
			restore_defaults(run, company)
			if own_company and company and frappe.db.exists("Company", company):
				check_redis()
				delete_company_transactions(company, log)
			skipped = delete_registered(run, log)
	except DemoDataError:
		run.set_status("Failed", error=frappe.get_traceback())
		raise
	except Exception as e:
		frappe.db.rollback()
		run.set_status("Failed", error=frappe.get_traceback())
		raise DemoDataError(f"Uninstall of {run.name} failed: {e}. Re-run uninstall to continue.") from e

	run.set_status("Uninstalled", counts=json.dumps(run.counts(), indent=1))
	if skipped:
		log(f"{len(skipped)} record(s) were kept because other data links to them:")
		for line in skipped:
			log(f"  {line}")
	return skipped


def restore_defaults(run: Run, company: str):
	from demo_data.setup.company import set_default_company

	default = frappe.db.get_single_value("Global Defaults", "default_company")
	demo = frappe.db.get_single_value("Global Defaults", "demo_company")
	if default != company and demo != company:
		return
	new_default = default
	if default == company and not run.params.get("use_wizard_company"):
		new_default = run.params.get("previous_default_company")
		if not (new_default and frappe.db.exists("Company", new_default)) or new_default == company:
			new_default = frappe.db.get_value("Company", {"name": ["!=", company]})
	frappe.db.set_single_value("Global Defaults", "demo_company", None if demo == company else demo)
	set_default_company(new_default)
	frappe.db.commit()


def delete_company_transactions(company: str, log=print):
	"""ERPNext's Transaction Deletion Record, run in-process like erpnext.setup.demo does."""
	from erpnext.setup.demo import create_transaction_deletion_record

	if not any(
		frappe.db.exists(dt, {"company": company})
		for dt in (*LEDGERS, "Sales Invoice", "Purchase Invoice", "Payment Entry")
	):
		return
	log(f"Deleting transactions of {company} (Transaction Deletion Record)")
	create_transaction_deletion_record(company)
	frappe.db.commit()
	# TDR's own status is unreliable (F-20); judge by what is left.
	left = {dt: frappe.db.count(dt, {"company": company}) for dt in LEDGERS}
	left = {dt: n for dt, n in left.items() if n}
	if left:
		from demo_data.service import DemoDataError

		raise DemoDataError(f"Transaction Deletion Record left ledger rows for {company}: {left}")


def delete_registered(run: Run, log=print) -> list[str]:
	skipped = []
	for rec in run.records(states=("Created", "Submitted", "Skipped"), reverse=True):
		doctype, name = rec.ref_doctype, rec.ref_name
		if not (doctype and name and frappe.db.exists(doctype, name)):
			run.set_record_state(rec.name, "Deleted")
			continue
		reason = blocker(doctype, name)
		if not reason:
			try:
				if doctype == "Company":
					delete_company_addresses(name)
					delete_template_rows(name)
				frappe.delete_doc(doctype, name, ignore_permissions=True)
				run.set_record_state(rec.name, "Deleted")
				frappe.db.commit()
				continue
			except LinkExistsError as e:
				frappe.db.rollback()
				reason = str(e)
		run.set_record_state(rec.name, "Skipped", reason)
		frappe.db.commit()
		skipped.append((rec.name, doctype, name, reason))

	# A record kept because something linked to it may have gone with a later
	# deletion; e.g. Company.on_trash deletes the company's accounts.
	kept = []
	for record_name, doctype, name, reason in skipped:
		if frappe.db.exists(doctype, name):
			kept.append(f"{doctype} {name}: {frappe.utils.strip_html(reason)[:200]}")
		else:
			run.set_record_state(record_name, "Deleted")
	frappe.db.commit()
	return kept


def blocker(doctype: str, name: str) -> str | None:
	"""Why a record must be kept, for cases frappe's link check does not cover."""
	if doctype == "Fiscal Year":
		start, end = frappe.db.get_value("Fiscal Year", name, ["year_start_date", "year_end_date"])
		n = frappe.db.count("GL Entry", {"posting_date": ["between", [start, end]], "is_cancelled": 0})
		if n:
			return f"{n} GL entries of other companies fall in this fiscal year"
	return None


def delete_company_addresses(company: str):
	"""A company's own Address blocks deleting the company (F-21)."""
	for address in frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Company", "link_name": company, "parenttype": "Address"},
		pluck="parent",
	):
		links = frappe.db.count("Dynamic Link", {"parent": address, "parenttype": "Address"})
		if links == 1:
			frappe.delete_doc("Address", address, ignore_permissions=True)
