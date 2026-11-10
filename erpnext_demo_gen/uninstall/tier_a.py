"""Tier A uninstall: remove a run's transactions one by one, using the registry (design 5.9).

For demo data generated into a company the user keeps (--use-wizard-company), so
ERPNext's company-wide Transaction Deletion Record cannot be used. Walking the
registry newest first, each submitted or cancelled document is removed the way
Transaction Deletion Record removes rows: its ledger rows (GL, payment ledger,
stock ledger, ...) are deleted, then the document and its child rows. Nothing is
cancelled, so no reversal entries or reposts are created.

A document is kept, and reported, when anything outside the run still refers to
it, e.g. a payment the user made against a demo invoice. Afterwards, bins are
recomputed for every item and warehouse the removed stock entries touched, and
where the user's own stock entries follow the removed ones, valuation is
reposted from the earliest removed date.
"""

import frappe
from frappe.exceptions import LinkExistsError
from frappe.model.delete_doc import get_dynamic_linked_docs, get_linked_docs

# rows that belong to a voucher and go with it: (doctype, voucher type field, voucher no field)
VOUCHER_ROWS = (
	("GL Entry", "voucher_type", "voucher_no"),
	("Payment Ledger Entry", "voucher_type", "voucher_no"),
	("Advance Payment Ledger Entry", "voucher_type", "voucher_no"),
	("Stock Ledger Entry", "voucher_type", "voucher_no"),
	("Serial and Batch Bundle", "voucher_type", "voucher_no"),
	("Repost Item Valuation", "voucher_type", "voucher_no"),
)
# references that never block removal: ledger rows go with their voucher, logs follow the document
IGNORED_REFERENCES = {dt for dt, _, _ in VOUCHER_ROWS} | {
	"Version",
	"Comment",
	"Communication",
	"ToDo",
	"Deleted Document",
	"Transaction Deletion Record Details",
}


class StockTouch:
	"""Item and warehouse pairs whose stock entries were removed, with the earliest posting."""

	def __init__(self):
		self.earliest = {}

	def add(self, item_code, warehouse, posting_datetime):
		key = (item_code, warehouse)
		if key not in self.earliest or posting_datetime < self.earliest[key]:
			self.earliest[key] = posting_datetime


def outside_references(doc, run_docs: set) -> list[str]:
	refs = get_linked_docs(doc) + get_dynamic_linked_docs(doc)
	return [
		f"{r['reference_doctype']} {r['reference_docname']}"
		for r in refs
		if r["reference_doctype"] not in IGNORED_REFERENCES
		and (r["reference_doctype"], r["reference_docname"]) not in run_docs
	]


def remove_transaction(doctype: str, name: str, run_docs: set, stock: StockTouch):
	"""Delete a submitted or cancelled document with its ledger rows; raise LinkExistsError if referenced."""
	doc = frappe.get_doc(doctype, name)
	blockers = outside_references(doc, run_docs)
	if blockers:
		raise LinkExistsError(f"referred to by {', '.join(blockers[:3])}")

	for row in frappe.get_all(
		"Stock Ledger Entry",
		filters={"voucher_type": doctype, "voucher_no": name},
		fields=["item_code", "warehouse", "posting_datetime"],
	):
		stock.add(row.item_code, row.warehouse, row.posting_datetime)

	for ledger, type_field, no_field in VOUCHER_ROWS:
		if frappe.db.table_exists(ledger):
			frappe.db.delete(ledger, {type_field: doctype, no_field: name})
	hard_delete(doc)


def hard_delete(doc):
	"""Remove a document and its child rows without the submitted-document check, as
	Transaction Deletion Record does, plus the logs that follow it."""
	for df in doc.meta.get_table_fields():
		frappe.db.delete(df.options, {"parent": doc.name, "parenttype": doc.doctype})
	frappe.db.delete(doc.doctype, {"name": doc.name})
	frappe.db.delete("Version", {"ref_doctype": doc.doctype, "docname": doc.name})
	frappe.db.delete("Comment", {"reference_doctype": doc.doctype, "reference_name": doc.name})
	frappe.db.delete("ToDo", {"reference_type": doc.doctype, "reference_name": doc.name})


def settle_stock(company: str, stock: StockTouch, log=print):
	"""Bring bins and valuation back in line after stock entries were removed.

	Where entries of other documents remain for an item and warehouse, valuation and
	the bin's actual quantity are reposted from the earliest removed entry, and the
	bin's reserved and ordered quantities are recomputed. Where none remain, the bin
	is deleted, as Transaction Deletion Record does; a stale bin would block deleting
	the item and the warehouse. (ERPNext's repost_stock is not used for the actual
	quantity: in v16 it only queues a repost from 1900-01-01.)
	"""
	from erpnext.controllers.stock_controller import create_repost_item_valuation_entry
	from erpnext.stock.stock_balance import repost_stock

	from erpnext_demo_gen.service import process_reposts

	reposts = 0
	for (item_code, warehouse), earliest in sorted(stock.earliest.items()):
		if not frappe.db.exists("Stock Ledger Entry", {"item_code": item_code, "warehouse": warehouse}):
			frappe.db.delete("Bin", {"item_code": item_code, "warehouse": warehouse})
			continue
		create_repost_item_valuation_entry(
			{
				"based_on": "Item and Warehouse",
				"item_code": item_code,
				"warehouse": warehouse,
				"posting_date": earliest.date(),
				"posting_time": earliest.time(),
				"company": company,
				"allow_zero_rate": 1,
			}
		)
		repost_stock(item_code, warehouse, only_bin=True)
		reposts += 1
	frappe.db.commit()
	if reposts:
		log(f"Reposting {reposts} item and warehouse pair(s) that also hold non-demo stock entries")
		process_reposts(company, log)


def is_transaction(doctype: str) -> bool:
	return bool(frappe.get_meta(doctype).is_submittable)


def run_documents(run) -> set:
	rows = frappe.get_all(
		"Demo Data Record",
		filters={"run": run.name, "state": ["in", ("Created", "Submitted", "Cancelled")]},
		fields=["ref_doctype", "ref_name"],
	)
	return {(r.ref_doctype, r.ref_name) for r in rows}


def refresh_company_sales(company: str):
	"""Company dashboards cache monthly sales; recompute without the removed invoices."""
	try:
		from erpnext.setup.doctype.company.company import (
			update_company_current_month_sales,
			update_company_monthly_sales,
		)

		update_company_current_month_sales(company)
		update_company_monthly_sales(company)
	except Exception:
		frappe.log_error("erpnext_demo_gen: could not refresh company sales history")


def remove_transactions(run, log=print) -> list[tuple]:
	"""Tier A for every transaction of the run, newest first. Returns kept (record, doctype, name, reason)."""
	run_docs = run_documents(run)
	stock = StockTouch()
	kept = []
	removed = 0
	from erpnext_demo_gen.progress import Progress

	records = [
		rec
		for rec in run.records(states=("Created", "Submitted", "Cancelled", "Skipped"), reverse=True)
		if rec.ref_doctype and rec.ref_name and is_transaction(rec.ref_doctype)
	]
	progress = Progress(len(records), log, "transactions removed")
	for i, rec in enumerate(records, 1):
		progress.update(i)
		doctype, name = rec.ref_doctype, rec.ref_name
		if not frappe.db.exists(doctype, name):
			run.set_record_state(rec.name, "Deleted")
			continue
		try:
			remove_transaction(doctype, name, run_docs, stock)
			run.set_record_state(rec.name, "Deleted")
			frappe.db.commit()
			removed += 1
		except LinkExistsError as e:
			frappe.db.rollback()
			run.set_record_state(rec.name, "Skipped", str(e))
			frappe.db.commit()
			kept.append((rec.name, doctype, name, str(e)))
	log(f"Removed {removed} transactions one by one (tier A)")
	settle_stock(run.doc.company, stock, log)
	refresh_company_sales(run.doc.company)
	frappe.db.commit()
	return kept
