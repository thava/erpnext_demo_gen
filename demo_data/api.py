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
	from demo_data.registry import active_runs
	from demo_data.service import DemoDataError, uninstall

	demo_company = frappe.db.get_single_value("Global Defaults", "demo_company")
	run = next((r for r in active_runs() if r.company == demo_company), None)
	if not run:
		from erpnext.setup.demo import clear_demo_data as erpnext_clear

		return erpnext_clear()
	try:
		uninstall(run.name, log=lambda msg: None)
	except DemoDataError as e:
		frappe.throw(str(e), title=_("Could Not Delete Demo Data"))
