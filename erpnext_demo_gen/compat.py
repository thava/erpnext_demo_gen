"""Small shims for ERPNext APIs that differ between major versions."""


def append_template_taxes(doc):
	"""Append the rows of the document's tax template (taxes_and_charges).

	v16 has AccountsController.append_taxes_from_master; develop (v17) removed it and
	moved the row lookup to erpnext.accounts.services.taxes.
	"""
	if hasattr(doc, "append_taxes_from_master"):
		doc.append_taxes_from_master()
		return
	if not doc.get("taxes_and_charges"):
		return
	from erpnext.accounts.services.taxes import _get_taxes_and_charges

	master = doc.meta.get_field("taxes_and_charges").options
	doc.extend("taxes", _get_taxes_and_charges(master, doc.taxes_and_charges) or [])


def mapper(module: str, name: str, required: bool = True):
	"""A "make X from Y" function, e.g. mapper("erpnext...purchase_order.purchase_order",
	"make_purchase_receipt").

	v16 keeps these in the doctype's own module; develop (v17) moved them to a mapper.py
	next to it. Returns None when not required and found in neither.
	"""
	import importlib

	for path in (module, module.rsplit(".", 1)[0] + ".mapper"):
		try:
			fn = getattr(importlib.import_module(path), name, None)
		except ImportError:
			continue
		if fn:
			return fn
	if required:
		raise ImportError(f"{name} is in neither {module} nor its mapper module")
	return None
