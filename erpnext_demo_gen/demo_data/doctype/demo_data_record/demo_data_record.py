# Copyright (c) 2026, Thava Alagu and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class DemoDataRecord(Document):
	"""One row per document a demo run created. Written by erpnext_demo_gen.registry only."""


def on_doctype_update():
	# resume and uninstall walk a run in seq order; verify looks documents up by reference
	frappe.db.add_index("Demo Data Record", ["run", "seq"])
	frappe.db.add_index("Demo Data Record", ["run", "plan_key"])
	frappe.db.add_index("Demo Data Record", ["ref_doctype", "ref_name"])
