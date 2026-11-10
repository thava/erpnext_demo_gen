# Copyright (c) 2026, Thava Alagu and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class DemoDataRun(Document):
	"""One row per install. Written by erpnext_demo_gen.registry only; kept after uninstall as an audit trail."""
