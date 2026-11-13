"""Builders: one function per PlannedDoc.builder, turning resolved params into a document.

A builder returns the inserted (or submitted) document. When a suitable document
already exists and is not ours (a shared item group, a payment terms template),
it returns that document with `flags.demo_reused` set; the writer then records
it as Reused, so dependants can use it but uninstall leaves it alone.
"""

import frappe
from frappe.utils.nestedset import get_root_of
from erpnext_demo_gen.compat import append_template_taxes, mapper


def insert(doc):
	doc.flags.notify_update = False  # no realtime events while generating (M-6)
	doc.insert(ignore_permissions=True)
	return doc


def reused(doctype: str, name: str):
	doc = frappe.get_doc(doctype, name)
	doc.flags.demo_reused = True
	return doc


# ---------------------------------------------------------------- simple masters
def payment_terms(p, w, pd):
	if frappe.db.exists("Payment Terms Template", p.title):
		return reused("Payment Terms Template", p.title)
	return insert(
		frappe.get_doc(
			{
				"doctype": "Payment Terms Template",
				"template_name": p.title,
				"terms": [
					{
						"invoice_portion": 100,
						"due_date_based_on": "Day(s) after invoice date",
						"credit_days": p.days,
						"description": f"Full payment within {p.days} days",
					}
				],
			}
		)
	)


def item_group(p, w, pd):
	if frappe.db.exists("Item Group", p.name):
		return reused("Item Group", p.name)
	return insert(
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": p.name,
				"parent_item_group": get_root_of("Item Group"),
				"is_group": 0,
			}
		)
	)


# ---------------------------------------------------------------- parties
def _group(doctype: str, preferred: str) -> str:
	if frappe.db.exists(doctype, {"name": preferred, "is_group": 0}):
		return preferred
	return frappe.db.get_value(doctype, {"is_group": 0}) or get_root_of(doctype)


def _add_contact(party_doc, contact: dict | None):
	"""A named contact person; ERPNext deletes it with the party (delete_contact_and_address)."""
	if not contact:
		return
	doc = frappe.get_doc(
		{
			"doctype": "Contact",
			"first_name": contact["first_name"],
			"last_name": contact.get("last_name"),
			"is_primary_contact": 1,
			"email_ids": [{"email_id": contact["email"], "is_primary": 1}] if contact.get("email") else [],
			"phone_nos": [{"phone": contact["mobile"], "is_primary_mobile_no": 1}]
			if contact.get("mobile")
			else [],
			"links": [{"link_doctype": party_doc.doctype, "link_name": party_doc.name}],
		}
	)
	insert(doc)
	field = f"{party_doc.doctype.lower()}_primary_contact"
	party_doc.db_set(
		{field: doc.name, "email_id": contact.get("email"), "mobile_no": contact.get("mobile")},
		update_modified=False,
	)


def supplier(p, w, pd):
	doc = insert(
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": p.name,
				"supplier_type": p.type,
				"supplier_group": _group("Supplier Group", p.group),
				**w.locale.party_fields(p, w),
			}
		)
	)
	_add_contact(doc, p.get("contact"))
	return doc


def customer(p, w, pd):
	doc = insert(
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": p.name,
				"customer_type": p.type,
				"customer_group": _group("Customer Group", p.group),
				"territory": w.territory,
				"payment_terms": p.get("payment_terms"),
				**w.locale.party_fields(p, w),
			}
		)
	)
	_add_contact(doc, p.get("contact"))
	return doc


# ---------------------------------------------------------------- items
def item(p, w, pd):
	code = p.code
	n = 1
	while frappe.db.exists("Item", code):  # someone else's item with our code
		n += 1
		code = f"{p.code}-{n}"
	warehouse = _warehouse(p, w)
	defaults = {"company": w.company, "default_warehouse": warehouse}
	if p.get("expense_account"):  # own-use supplies: expensed when issued (stock) or billed
		defaults["expense_account"] = _account(w.company, p.expense_account)
	defaults.update(w.locale.item_defaults(p, w))
	is_stock = p.get("is_stock", 1)
	return insert(
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": p.name,
				"description": p.name,
				"item_group": p.group,
				"stock_uom": p.uom,
				"is_stock_item": is_stock,
				"is_sales_item": p.get("is_sales_item", 1),
				"include_item_in_manufacturing": 0,
				"valuation_rate": p.cost,
				**w.locale.item_fields(p, w),
				"item_defaults": [defaults],
				"supplier_items": [{"supplier": s} for s in p.suppliers],
				"reorder_levels": [
					{
						"warehouse": warehouse,
						"warehouse_reorder_level": p.reorder["min"],
						"warehouse_reorder_qty": p.reorder["max"] - p.reorder["min"],
						"material_request_type": "Purchase",
					}
				]
				if is_stock and p.get("reorder")
				else [],
			}
		)
	)


def _warehouse(p, w) -> str:
	"""The planned warehouse (pack name, e.g. "Office Stores") or the company default."""
	return f"{p.warehouse} - {w.abbr}" if p.get("warehouse") else w.default_warehouse


def item_price(p, w, pd):
	price_list = w.selling_price_list if p.list == "selling" else w.buying_price_list
	return insert(
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": p.item,
				"price_list": price_list,
				"price_list_rate": p.rate,
				"uom": frappe.db.get_value("Item", p.item, "stock_uom"),
				# valid_from defaults to today, which hides the price from back-dated documents
				"valid_from": w.start_date,
			}
		)
	)


# ---------------------------------------------------------------- transactions
# Every transaction carries the planned posting date and a strictly increasing
# posting time, so documents are written in ledger order and nothing is
# back-dated (A-9). Documents are built with ERPNext's own mappers where one
# exists (M-12).


def _dated(doc, pd):
	for fieldname in ("posting_date", "transaction_date"):
		if doc.meta.has_field(fieldname):
			doc.set(fieldname, pd.posting_date)
	if doc.meta.has_field("posting_time"):
		doc.posting_time = pd.posting_time
	if doc.meta.has_field("set_posting_time"):
		doc.set_posting_time = 1
	return doc


def _save(doc, pd, submit=True, fill_taxes=False, tax_inclusive=False):
	"""Insert, optionally fill tax rows, then submit.

	Orders built on the server get a tax template during validation but no tax
	rows (F-16). Rows are appended after the first save, as a user would, and the
	second save lets ERPNext and india_compliance compute every amount; computing
	them before insert leaves india_compliance's per-row GST amounts stale. A locale
	may fill the rows itself before insert (Germany: F-48); they are kept.
	"""
	_dated(doc, pd)
	if fill_taxes and tax_inclusive and doc.get("taxes"):  # rows the locale filled
		for row in doc.taxes:
			row.included_in_print_rate = 1
	insert(doc)
	if fill_taxes and doc.get("taxes_and_charges") and not doc.get("taxes"):
		append_template_taxes(doc)
		if tax_inclusive:  # retail shelf prices include GST
			for row in doc.taxes:
				row.included_in_print_rate = 1
		doc.save(ignore_permissions=True)
	if submit:
		doc.submit()
	return doc


def _lines(lines, w, date_field=None, when=None, warehouse=None):
	rows = []
	for line in lines:
		row = {"item_code": line["item"], "qty": line["qty"], "warehouse": warehouse or w.default_warehouse}
		if line.get("rate") is not None:
			row["rate"] = line["rate"]
		if date_field:
			row[date_field] = when
		rows.append(row)
	return rows


def _account(company: str, account_name: str) -> str:
	name = frappe.db.get_value("Account", {"company": company, "account_name": account_name, "is_group": 0})
	if not name:
		frappe.throw(f"Account {account_name!r} not found for {company}")
	return name


def funding_entry(p, w, pd):
	accounts = [{"account": w.bank_ledger, "debit_in_account_currency": p.share_capital + p.term_loan}]
	if p.share_capital:
		accounts.append(
			{"account": _account(w.company, w.locale.funding_accounts["share_capital"]), "credit_in_account_currency": p.share_capital}
		)
	if p.term_loan:
		accounts.append(
			{"account": _account(w.company, w.locale.funding_accounts["term_loan"]), "credit_in_account_currency": p.term_loan}
		)
	doc = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": w.company,
			"user_remark": "Owner's capital and term loan",
			"accounts": accounts,
		}
	)
	_save(doc, pd)
	doc.db_set("clearance_date", pd.posting_date)  # the money is in the bank on day one
	return doc


# ---------------------------------------------------------------- buying
def material_request(p, w, pd):
	doc = frappe.get_doc(
		{
			"doctype": "Material Request",
			"material_request_type": p.get("type") or "Purchase",
			"company": w.company,
			"schedule_date": p.schedule_date,
			"items": _lines(
				[{**line, "rate": None} for line in p.lines],
				w,
				"schedule_date",
				p.schedule_date,
				warehouse=_warehouse(p, w),
			),
		}
	)
	if p.get("department"):  # a staff request from a department
		doc.title = f"{p.department}: supplies"
	return _save(doc, pd)


def stock_issue(p, w, pd):
	"""Issue a staff request's supplies from their store (Stock Entry, Material Issue);
	the cost goes to the items' expense account."""
	make_stock_entry = mapper("erpnext.stock.doctype.material_request.material_request", "make_stock_entry")

	doc = make_stock_entry(p.material_request)
	qty = {line["item"]: line["qty"] for line in p.lines}
	for row in doc.items:
		row.qty = qty.get(row.item_code, row.qty)
		row.transfer_qty = row.qty * (row.conversion_factor or 1)
	_dated(doc, pd)
	return _save(doc, pd)


def purchase_invoice_from_order(p, w, pd):
	"""A bill straight from the order, for non-stock consumables (nothing to receive)."""
	make_purchase_invoice = mapper("erpnext.buying.doctype.purchase_order.purchase_order", "make_purchase_invoice")

	doc = make_purchase_invoice(p.purchase_order)
	doc.bill_no = p.bill_no
	doc.bill_date = pd.posting_date
	_dated(doc, pd)
	doc.due_date = frappe.utils.add_days(pd.posting_date, 30)
	doc.payment_schedule = []
	return _submit_purchase_invoice(doc, w, pd)


def purchase_order(p, w, pd):
	if p.get("material_request"):
		make_purchase_order = mapper("erpnext.stock.doctype.material_request.material_request", "make_purchase_order")

		doc = make_purchase_order(p.material_request)
		doc.supplier = p.supplier
		rates = {line["item"]: line["rate"] for line in p.lines}
		for row in doc.items:
			row.rate = rates.get(row.item_code, row.rate)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Purchase Order",
				"supplier": p.supplier,
				"company": w.company,
				"schedule_date": p.schedule_date,
				"items": _lines(p.lines, w, "schedule_date", p.schedule_date, warehouse=_warehouse(p, w)),
			}
		)
	doc.schedule_date = p.schedule_date
	w.locale.purchase_taxes(doc, w)  # India --unregistered: the no-ITC template (F-38)
	return _save(doc, pd, fill_taxes=True)


def purchase_receipt(p, w, pd):
	make_purchase_receipt = mapper("erpnext.buying.doctype.purchase_order.purchase_order", "make_purchase_receipt")

	return _save(make_purchase_receipt(p.purchase_order), pd)


def purchase_invoice(p, w, pd):
	make_purchase_invoice = mapper("erpnext.stock.doctype.purchase_receipt.purchase_receipt", "make_purchase_invoice")

	doc = make_purchase_invoice(p.purchase_receipt)
	doc.bill_no = p.bill_no
	doc.bill_date = pd.posting_date
	_dated(doc, pd)
	doc.due_date = frappe.utils.add_days(pd.posting_date, 30)
	doc.payment_schedule = []
	return _submit_purchase_invoice(doc, w, pd)


def _submit_purchase_invoice(doc, w, pd):
	"""Save, let the locale complete it (UAE: recoverable VAT), then submit."""
	_save(doc, pd, submit=False)
	if w.locale.finish_purchase_invoice(doc, w):
		doc.save(ignore_permissions=True)
	doc.submit()
	return doc


def pay_supplier(p, w, pd):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	doc = get_payment_entry("Purchase Invoice", p.invoice, reference_date=pd.posting_date)
	_payment_method(doc, w, p, pd, "paid_from")
	return _cleared(_save(doc, pd), p)


# ---------------------------------------------------------------- selling
def quotation(p, w, pd):
	doc = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": "Customer",
			"party_name": p.customer,
			"company": w.company,
			"valid_till": frappe.utils.add_days(pd.posting_date, 30),
			"items": _lines(p.lines, w),
		}
	)
	w.locale.sales_taxes(doc, w)
	return _save(doc, pd, fill_taxes=True)


def sales_order(p, w, pd):
	if p.get("quotation"):
		quotation = "erpnext.selling.doctype.quotation.quotation"
		# The public make_sales_order refuses quotations whose valid_till is before
		# *today*, which every historical quotation is. Its inner mapper does the same
		# mapping without that check (F-27; watch for upstream drift).
		inner = mapper(quotation, "_make_sales_order", required=False)
		if inner:
			doc = inner(p.quotation, ignore_permissions=True)
		else:
			doc = mapper(quotation, "make_sales_order")(p.quotation)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": p.customer,
				"company": w.company,
				"items": _lines(p.lines, w),
			}
		)
	doc.delivery_date = p.delivery_date
	for row in doc.items:
		row.delivery_date = p.delivery_date
		row.warehouse = row.warehouse or w.default_warehouse
	w.locale.sales_taxes(doc, w)
	return _save(doc, pd, fill_taxes=True)


def delivery_note(p, w, pd):
	make_delivery_note = mapper("erpnext.selling.doctype.sales_order.sales_order", "make_delivery_note")

	doc = make_delivery_note(p.sales_order)
	if p.get("fraction"):
		for row in doc.items:
			row.qty = max(1, int(row.qty * p.fraction))
	for row in doc.items:
		row.warehouse = row.warehouse or w.default_warehouse
	return _save(doc, pd)


def _credit_terms(doc, days):
	"""Recompute the due date from the planned posting date.

	Mappers fill due_date and the payment schedule from *today*; after moving the
	posting date back they would exceed the customer's terms. Clearing them lets
	validation recompute from the payment terms template, or we set it from days.
	"""
	doc.payment_schedule = []
	doc.due_date = None
	if not doc.get("payment_terms_template"):
		doc.due_date = frappe.utils.add_days(doc.posting_date, days or 0)


def invoice_from_delivery(p, w, pd):
	make_sales_invoice = mapper("erpnext.stock.doctype.delivery_note.delivery_note", "make_sales_invoice")

	doc = make_sales_invoice(p.delivery_note)
	_dated(doc, pd)
	_credit_terms(doc, p.credit_days)
	return _save(doc, pd)


def counter_sales_invoice(p, w, pd):
	doc = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"customer": p.customer,
			"company": w.company,
			"update_stock": 1,
			"set_warehouse": w.default_warehouse,
			"items": _lines(p.lines, w),
		}
	)
	_dated(doc, pd)
	_credit_terms(doc, p.credit_days)
	w.locale.sales_taxes(doc, w)
	return _save(doc, pd, submit=not p.draft, fill_taxes=True, tax_inclusive=w.locale.prices_include_tax)


def sales_return(p, w, pd):
	make_sales_return = mapper("erpnext.accounts.doctype.sales_invoice.sales_invoice", "make_sales_return")

	doc = make_sales_return(p.against)
	doc.items = [row for row in doc.items if row.item_code == p.item][:1]
	doc.items[0].qty = -abs(p.qty)
	_dated(doc, pd)
	_credit_terms(doc, 0)
	return _save(doc, pd)


def receive_payment(p, w, pd):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	outstanding = frappe.db.get_value("Sales Invoice", p.invoice, "outstanding_amount")
	amount = round(outstanding * p.fraction) if p.get("fraction") else None
	doc = get_payment_entry("Sales Invoice", p.invoice, party_amount=amount, reference_date=pd.posting_date)
	_payment_method(doc, w, p, pd, "paid_to")
	return _cleared(_save(doc, pd), p)


def refund(p, w, pd):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	doc = get_payment_entry("Sales Invoice", p.credit_note, reference_date=pd.posting_date)
	_payment_method(doc, w, p, pd, "paid_from")
	return _cleared(_save(doc, pd), p)


def _payment_method(doc, w, p, pd, field: str):
	"""Mode, account and bank reference as planned. Bank payments always use the demo's
	own bank accounts, never the company's default (which may be the user's).

	Plans made before payment methods existed carry only "cash"."""
	mode = p.get("mode") or ("Cash" if p.get("cash") else "Wire Transfer")
	doc.mode_of_payment = mode
	if mode == "Cash":
		doc.set(field, w.cash_account)
		doc.bank_account = None
		return
	target = w.accounts.get(p.get("account") or "main") or {"ledger": w.bank_ledger, "bank_account": w.bank_account}
	doc.set(field, target["ledger"])
	if target.get("bank_account"):
		doc.bank_account = target["bank_account"]
	doc.reference_no = p.get("reference") or f"UTR{pd.seq:07d}"
	doc.reference_date = pd.posting_date


def bank_transfer(p, w, pd):
	"""Weekly Internal Transfer into the main account: the collection account's balance
	(swept by NEFT) or the cash in hand (deposited at the branch)."""
	from erpnext.accounts.utils import get_balance_on

	source = w.accounts["collection"]["ledger"] if p.source == "collection" else w.cash_account
	target = w.accounts["main"]["ledger"]
	amount = get_balance_on(account=source, date=pd.posting_date, company=w.company)
	if amount <= 0:
		frappe.throw(f"Nothing to transfer from {source} on {pd.posting_date} (balance {amount})")
	doc = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Internal Transfer",
			"company": w.company,
			"mode_of_payment": "Wire Transfer" if p.source == "collection" else "Cash",
			"paid_from": source,
			"paid_to": target,
			"paid_amount": amount,
			"received_amount": amount,
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
			"bank_account": w.accounts["main"]["bank_account"],
			"reference_no": p.reference,
			"reference_date": pd.posting_date,
			"remarks": "Weekly sweep of the collection account"
			if p.source == "collection"
			else "Weekly cash deposit",
		}
	)
	return _cleared(_save(doc, pd), p)


def _cleared(doc, p):
	"""The date the bank cleared the payment, as the Bank Reconciliation Tool would set it."""
	if p.get("clearance_date"):
		doc.db_set("clearance_date", p.clearance_date)
	return doc


def cancel(p, w, pd):
	doc = frappe.get_doc(p.doctype, p.doc)
	if doc.docstatus == 2:  # cancelled already (the repost below commits; a resume may repeat this step)
		return doc
	doc.flags.notify_update = False
	doc.cancel()
	# A cancellation queues a stock repost (F-31). Run it now, before the scheduler's
	# worker picks it up and updates Bin rows under the writer (F-34).
	from erpnext_demo_gen.service import process_reposts

	process_reposts(w.company, log=lambda msg: None)
	return doc
