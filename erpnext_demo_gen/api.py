"""Desk entry points."""

import frappe
from frappe import _


@frappe.whitelist(methods=["POST"])
def clear_demo_data():
	"""Replaces erpnext.setup.demo.clear_demo_data behind the desk's "Delete Demo Data" button (DEC-19).

	ERPNext's version only knows its own sample masters, so for a company we
	created we run our uninstall instead; for any other demo company we defer to
	ERPNext.
	"""
	frappe.only_for("System Manager")
	from erpnext_demo_gen.registry import active_runs
	from erpnext_demo_gen.service import DemoDataError, uninstall

	demo_company = frappe.db.get_single_value("Global Defaults", "demo_company")
	run = next((r for r in active_runs() if r.company == demo_company), None)
	if not run:
		from erpnext.setup.demo import clear_demo_data as erpnext_clear

		return erpnext_clear()
	try:
		uninstall(run.name, log=lambda msg: None)
	except DemoDataError as e:
		frappe.throw(str(e), title=_("Could Not Delete Demo Data"))
	# Uninstall keeps records that other data still refers to; say so instead of "cleared".
	status, error = frappe.db.get_value("Demo Data Run", run.name, ["status", "error"])
	if status != "Uninstalled":
		frappe.throw(
			_("Demo data was removed except what other data still refers to:")
			+ f"<br><pre>{frappe.utils.escape_html(error or '')}</pre>"
			+ _("Remove those references and click Delete Demo Data again."),
			title=_("Demo Data Not Fully Deleted"),
		)
