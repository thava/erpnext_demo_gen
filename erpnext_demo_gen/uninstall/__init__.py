"""Uninstall a demo run (M-9, design 5.9).

Order, as established by the Phase 0 spike (section 6.2):
1. Restore the previous default company and clear Global Defaults.demo_company
   (Company.on_trash refuses to delete the registered demo company).
2. Transactions. Tier B (default for a company the run created): ERPNext's
   Transaction Deletion Record for the whole company, in-process. Tier A (for
   --use-wizard-company runs, or with registry_only): each registered
   transaction with its ledger rows, newest first (tier_a.py); the user's own
   documents in the same company are untouched.
3. Walk the registry in reverse creation order and delete what remains. A record
   that is still linked from non-demo data is skipped and reported, not forced.
   The company comes last because it was created first.
"""

from collections import defaultdict

import frappe
from frappe.exceptions import LinkExistsError

from erpnext_demo_gen.jobs import inline_jobs
from erpnext_demo_gen.registry import Run
from erpnext_demo_gen.setup.tax_templates import delete_template_rows

LEDGERS = ("GL Entry", "Stock Ledger Entry", "Payment Ledger Entry")


def uninstall_run(run: Run, log=print, registry_only: bool = False, no_backup: bool = False):
	from erpnext_demo_gen.progress import duration, remove_seconds
	from erpnext_demo_gen.service import DemoDataError, check_redis

	company = run.doc.company
	own_company = not run.params.get("use_wizard_company")
	tier_b = own_company and not registry_only and company and frappe.db.exists("Company", company)
	one_by_one = not tier_b
	if not own_company and not no_backup:
		safety_backup(log)
	run.set_status("Uninstalling", error="")
	documents = sum(
		n for states in run.counts().values() for st, n in states.items() if st in ("Created", "Submitted")
	)
	how = "one by one from the registry" if one_by_one else "with the demo company"
	log(
		f"Removing {documents} documents of {run.name} {how}; this takes about "
		f"{duration(remove_seconds(documents, one_by_one))}. Please wait."
	)
	try:
		with inline_jobs():
			restore_defaults(run, company)
			kept_transactions = []
			if tier_b:
				check_redis()
				delete_company_transactions(company, log)
			else:
				from erpnext_demo_gen.uninstall.tier_a import remove_transactions

				kept_transactions = remove_transactions(run, log)
			restore_banking(run, company)
			restore_gst_settings(run)
			log("Deleting the demo's customers, suppliers, items and other setup records...")
			skipped = [
				f"{doctype} {name}: {frappe.utils.strip_html(reason)[:200]}"
				for _, doctype, name, reason in kept_transactions
			] + delete_registered(run, log)
	except DemoDataError:
		run.set_status("Failed", error=frappe.get_traceback())
		raise
	except Exception as e:
		frappe.db.rollback()
		run.set_status("Failed", error=frappe.get_traceback())
		raise DemoDataError(f"Uninstall of {run.name} failed: {e}. Re-run uninstall to continue.") from e

	if skipped:
		# Not "Uninstalled": something of the run is still on the site. Re-running
		# uninstall retries these once whatever holds them is gone.
		run.set_status(
			"Failed", error=f"Kept {len(skipped)} record(s):\n" + "\n".join(skipped), totals=True
		)
		if own_company and company and frappe.db.exists("Company", company):
			# keep the desk's "Delete Demo Data" button available for another try
			frappe.db.set_single_value("Global Defaults", "demo_company", company)
			frappe.db.commit()
		log(f"{len(skipped)} record(s) were kept because other data links to them:")
		for line in skipped:
			log(f"  {line}")
		log("Remove those references and run uninstall again.")
	else:
		run.set_status("Uninstalled", totals=True)  # counts keeps what the install created
	return skipped


def restore_defaults(run: Run, company: str):
	from erpnext_demo_gen.setup.company import set_default_company

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


def restore_banking(run: Run, company: str):
	"""Undo what setup_banking changed in a company that stays (wizard-company runs)."""
	banking = run.params.get("banking") or {}
	if not (company and frappe.db.exists("Company", company)):
		return
	if banking.get("set_default_bank"):
		frappe.db.set_value("Company", company, "default_bank_account", banking.get("previous_default_bank"))
	for mode in banking.get("modes_added") or []:
		frappe.db.delete("Mode of Payment Account", {"parent": mode, "company": company})
	frappe.db.commit()


def restore_gst_settings(run: Run):
	"""Put back the GST Settings values setup changed (see setup.company.enable_sez)."""
	for field, value in (run.params.get("gst_settings") or {}).items():
		frappe.db.set_single_value("GST Settings", field, value)
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
		from erpnext_demo_gen.service import DemoDataError

		raise DemoDataError(f"Transaction Deletion Record left ledger rows for {company}: {left}")


def delete_registered(run: Run, log=print) -> list[str]:
	skipped = []
	for rec in run.records(states=("Created", "Submitted", "Skipped"), reverse=True):
		doctype, name = rec.ref_doctype, rec.ref_name
		if not (doctype and name and frappe.db.exists(doctype, name)):
			run.set_record_state(rec.name, "Deleted")
			continue
		if frappe.get_meta(doctype).is_submittable:
			continue  # a transaction that tier A kept; already reported
		reason = blocker(doctype, name)
		if not reason:
			try:
				if doctype == "Company":
					delete_company_addresses(name)
					delete_template_rows(name)
					release_company_links(name, log)
				frappe.delete_doc(doctype, name, ignore_permissions=True)
				run.set_record_state(rec.name, "Deleted")
				frappe.db.commit()
				continue
			except frappe.ValidationError as e:  # LinkExistsError and on_trash refusals alike
				frappe.db.rollback()
				frappe.local.message_log = []
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


def safety_backup(log=print):
	"""Back up the site before removing demo data from the user's own company (wizard
	mode), as bench drop-site and uninstall-app do; skipped with --no-backup."""
	from frappe.utils.backups import scheduled_backup

	log("Backing up the site first, since the demo data is in your own company (skip with --no-backup)")
	odb = scheduled_backup(ignore_files=True, ignore_conf=True, force=True)
	log(f"Backup: {odb.backup_path_db}")


def release_company_links(company: str, log=print):
	"""Before deleting a demo company: remove per-company rows other records keep for it.

	Apps undo what they add for a company in their Company on_trash handlers, which
	frappe.delete_doc runs before its link check (ERPNext: accounts, warehouses...;
	Healthcare: service units; HRMS: its company_data_to_be_ignored records). One gap:
	HRMS adds an Expense Claim Account row to every Expense Claim Type when a company
	is saved and does not remove it (F-40). Such child-table rows mean nothing without
	the company, so every child row that links to it is removed. Whole documents are
	left to their apps; anything still linked keeps the company, and it is reported.
	Only called for a company the demo created (tier B).
	"""
	fields = frappe.db.sql(
		"""select parent, fieldname from tabDocField where fieldtype = 'Link' and options = 'Company'
		union select dt, fieldname from `tabCustom Field` where fieldtype = 'Link' and options = 'Company'"""
	)
	removed = defaultdict(int)
	for doctype, field in fields:
		if not frappe.db.table_exists(doctype):
			continue
		meta = frappe.get_meta(doctype)
		if not meta.istable or not meta.has_field(field):
			continue
		for parenttype, n in frappe.db.sql(
			f"select parenttype, count(*) from `tab{doctype}` where `{field}` = %s group by parenttype", company
		):
			removed[f"{parenttype}: {doctype}"] += n
		frappe.db.delete(doctype, {field: company})
	if removed:
		log("Removed rows other records keep for the company: " + ", ".join(f"{k} ({n})" for k, n in sorted(removed.items())))


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
