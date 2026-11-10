"""Phase 0 runtime spike for erpnext_demo_gen. Run one step at a time:
bench --site demo-data.localhost execute "...spike.run" --kwargs '{"step": "company"}'
"""

import json
import time

import frappe
from frappe.utils import add_days, getdate

CO = "Spike Traders Pvt Ltd"
ABBR = "SPK"
CODES = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

NET_CALLS = []
JOBS = []


# ---------------------------------------------------------------- guards
def install_guards():
	import requests

	def no_net(self, request, **kw):
		NET_CALLS.append(request.url)
		raise RuntimeError(f"network call blocked: {request.url}")

	requests.Session.send = no_net

	orig = frappe.enqueue

	def spy(method, *a, **kw):
		JOBS.append(method if isinstance(method, str) else getattr(method, "__name__", str(method)))
		return orig(method, *a, **kw)

	frappe.enqueue = spy
	frappe.flags.mute_emails = True


def report_guards():
	print("NET_CALLS", NET_CALLS)
	from collections import Counter

	print("ENQUEUED", dict(Counter(JOBS)))


# ---------------------------------------------------------------- gstin
def gstin_check_char(first14):
	factor, total = 1, 0
	for ch in first14:
		d = factor * CODES.index(ch)
		total += d // 36 + d % 36
		factor = 2 if factor == 1 else 1
	return CODES[(36 - total % 36) % 36]


def make_pan(seed, entity="C", name_initial="S"):
	import random

	r = random.Random(seed)
	letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	return (
		"".join(r.choice(letters) for _ in range(3))
		+ entity
		+ name_initial
		+ f"{r.randint(0, 9999):04d}"
		+ r.choice(letters)
	)


def make_gstin(state_code, pan, entity_no="1"):
	first14 = f"{int(state_code):02d}{pan}{entity_no}Z"
	return first14 + gstin_check_char(first14)


def step_gstin():
	from india_compliance.gst_india.utils import is_valid_pan, validate_gst_category, validate_gstin

	ok = 0
	for i in range(500):
		pan = make_pan(i, entity="CPFH"[i % 4])
		g = make_gstin(1 + i % 37, pan)
		validate_gstin(g)
		validate_gst_category("Registered Regular", g)
		assert is_valid_pan(pan)
		ok += 1
	print("gstin ok", ok, "sample", make_gstin(33, make_pan(1)))


# ---------------------------------------------------------------- company
def step_company():
	if not frappe.db.exists("Company", CO):
		c = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": CO,
				"abbr": ABBR,
				"country": "India",
				"default_currency": "INR",
				"chart_of_accounts": "Standard",
				"default_gst_rate": "18.0",
			}
		).insert()
		addr = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": CO,
				"address_type": "Billing",
				"address_line1": "12 Anna Salai",
				"city": "Chennai",
				"state": "Tamil Nadu",
				"pincode": "600002",
				"country": "India",
				"gstin": make_gstin(33, make_pan(99, "C", "S")),
				"gst_category": "Registered Regular",
				"is_your_company_address": 1,
				"is_primary_address": 1,
				"links": [{"link_doctype": "Company", "link_name": CO}],
			}
		).insert()
		print("address", addr.name, addr.gstin)
	frappe.db.set_single_value("Global Defaults", "default_company", CO)
	frappe.db.set_default("company", CO)
	frappe.db.commit()
	c = frappe.get_doc("Company", CO)
	print("item tax", frappe.get_all("Item Tax Template", {"company": CO}, pluck="name"))
	print("sales tmpl", frappe.get_all("Sales Taxes and Charges Template", {"company": CO}, pluck="name"))
	print(
		"purchase tmpl", frappe.get_all("Purchase Taxes and Charges Template", {"company": CO}, pluck="name")
	)
	print(
		"gst accounts in settings",
		[r.account_type for r in frappe.get_single("GST Settings").gst_accounts if r.company == CO],
	)
	for f in [
		"default_customs_payable_account",
		"default_gst_expense_account",
		"default_cash_account",
		"default_bank_account",
		"default_receivable_account",
		"stock_received_but_not_billed",
		"default_inventory_account",
		"round_off_account",
		"cost_center",
	]:
		print(" ", f, c.get(f))
	print("warehouses", frappe.get_all("Warehouse", {"company": CO, "is_group": 0}, pluck="name"))
	print("default company now", frappe.db.get_default("company"))


# ---------------------------------------------------------------- masters
def ensure(doctype, name, data):
	if frappe.db.exists(doctype, name):
		return frappe.get_doc(doctype, name)
	return frappe.get_doc({"doctype": doctype, **data}).insert()


def step_masters():
	ensure(
		"Item Group",
		"Spike Furniture",
		{"item_group_name": "Spike Furniture", "parent_item_group": "All Item Groups"},
	)
	for code, hsn, rate in [("SPK-SOFA-3", "94016100", 72000), ("SPK-CHAIR", "94013000", 6500)]:
		ensure(
			"Item",
			code,
			{
				"item_code": code,
				"item_name": code.replace("SPK-", "Spike "),
				"item_group": "Spike Furniture",
				"stock_uom": "Nos",
				"is_stock_item": 1,
				"gst_hsn_code": hsn,
				"standard_rate": rate,
				"valuation_rate": rate * 0.6,
				"taxes": [{"item_tax_template": f"GST 18% - {ABBR}"}],
			},
		)
	parties = [
		("Customer", "Kaveri Interiors", 29, "Bengaluru", "Karnataka", "560001", "Registered Regular"),
		("Customer", "Marina Homes", 33, "Chennai", "Tamil Nadu", "600004", "Registered Regular"),
		("Customer", "Walk-in Customer", None, "Chennai", "Tamil Nadu", "600017", "Unregistered"),
		("Supplier", "Deccan Woodcraft", 27, "Pune", "Maharashtra", "411001", "Registered Regular"),
	]
	for i, (dt, name, st, city, state, pin, cat) in enumerate(parties):
		gstin = make_gstin(st, make_pan(1000 + i, "C", name[0])) if st else None
		data = {
			f"{dt.lower()}_name": name,
			f"{dt.lower()}_type": "Company",
			"gstin": gstin,
			"gst_category": cat,
			"_address_line1": f"{i + 1} Main Road",
			"city": city,
			"state": state,
			"pincode": pin,
			"country": "India",
		}
		if dt == "Customer":
			data["customer_group"] = "Commercial"
			data["territory"] = "India" if frappe.db.exists("Territory", "India") else "All Territories"
		else:
			data["supplier_group"] = (
				frappe.db.get_value("Supplier Group", {"is_group": 0}) or "All Supplier Groups"
			)
		d = ensure(dt, name, data)
		print(dt, d.name, d.gstin, d.gst_category, "addr:", d.get(f"{dt.lower()}_primary_address"))
	frappe.db.commit()


# ---------------------------------------------------------------- flows
def submit(doc, date):
	doc.set_posting_time = 1
	if doc.meta.has_field("posting_date"):
		doc.posting_date = date
	if doc.meta.has_field("transaction_date"):
		doc.transaction_date = date
	doc.flags.notify_update = False
	doc.insert()
	doc.submit()
	return doc


def step_flows():
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry
	from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_receipt
	from erpnext.selling.doctype.sales_order.sales_order import make_delivery_note
	from erpnext.stock.doctype.delivery_note.delivery_note import make_sales_invoice
	from erpnext.stock.doctype.purchase_receipt.purchase_receipt import make_purchase_invoice

	install_guards()
	c = frappe.get_doc("Company", CO)
	wh = f"Stores - {ABBR}"
	d0 = getdate("2026-05-04")

	# funding
	je = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"company": CO,
			"posting_date": d0,
			"voucher_type": "Journal Entry",
			"accounts": [
				{"account": c.default_cash_account, "debit_in_account_currency": 2500000},
				{
					"account": frappe.db.get_value(
						"Account", {"company": CO, "account_name": "Capital Stock"}
					),
					"credit_in_account_currency": 2500000,
				},
			],
		}
	)
	submit(je, d0)
	print("JE", je.name)

	po = frappe.get_doc(
		{
			"doctype": "Purchase Order",
			"company": CO,
			"supplier": "Deccan Woodcraft",
			"schedule_date": add_days(d0, 5),
			"items": [
				{
					"item_code": "SPK-SOFA-3",
					"qty": 5,
					"rate": 43000,
					"warehouse": wh,
					"schedule_date": add_days(d0, 5),
				},
				{
					"item_code": "SPK-CHAIR",
					"qty": 20,
					"rate": 3900,
					"warehouse": wh,
					"schedule_date": add_days(d0, 5),
				},
			],
		}
	)
	submit(po, d0)
	print("PO", po.name, po.taxes_and_charges, [(t.account_head, t.rate) for t in po.taxes], po.grand_total)
	pr = make_purchase_receipt(po.name)
	submit(pr, add_days(d0, 5))
	pi = make_purchase_invoice(pr.name)
	pi.bill_no = "DW-1001"
	pi.bill_date = add_days(d0, 5)
	submit(pi, add_days(d0, 5))
	pe = get_payment_entry("Purchase Invoice", pi.name)
	pe.reference_no, pe.reference_date = "NEFT1", add_days(d0, 20)
	submit(pe, add_days(d0, 20))
	print("PR", pr.name, "PI", pi.name, pi.grand_total, "PE", pe.name)

	so = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"company": CO,
			"customer": "Kaveri Interiors",
			"delivery_date": add_days(d0, 15),
			"items": [
				{
					"item_code": "SPK-SOFA-3",
					"qty": 2,
					"rate": 72000,
					"warehouse": wh,
					"delivery_date": add_days(d0, 15),
				}
			],
		}
	)
	submit(so, add_days(d0, 10))
	print("SO", so.name, so.taxes_and_charges, [(t.account_head, t.rate) for t in so.taxes], so.grand_total)
	dn = make_delivery_note(so.name)
	submit(dn, add_days(d0, 15))
	si = make_sales_invoice(dn.name)
	submit(si, add_days(d0, 15))
	print(
		"DN",
		dn.name,
		"SI",
		si.name,
		si.grand_total,
		"place_of_supply",
		si.place_of_supply,
		"ewaybill",
		si.get("ewaybill"),
	)
	pe2 = get_payment_entry("Sales Invoice", si.name)
	pe2.reference_no, pe2.reference_date = "UTR1", add_days(d0, 40)
	pe2.paid_amount = pe2.received_amount = 100000
	pe2.references[0].allocated_amount = 100000
	submit(pe2, add_days(d0, 40))
	si.reload()
	print("PE2", pe2.name, "SI outstanding", si.outstanding_amount, si.status)

	frappe.db.commit()
	report_guards()
	print("RIV", frappe.db.count("Repost Item Valuation", {"company": CO}))


# ---------------------------------------------------------------- benchmark
def step_bench(n=40):
	install_guards()
	n = int(n)
	wh = f"Stores - {ABBR}"
	d = getdate("2026-06-01")
	# stock up first
	se = frappe.get_doc(
		{
			"doctype": "Stock Entry",
			"stock_entry_type": "Material Receipt",
			"company": CO,
			"items": [{"item_code": "SPK-CHAIR", "qty": n * 3, "basic_rate": 3900, "t_warehouse": wh}],
		}
	)
	submit(se, d)
	frappe.db.commit()

	t = {}
	custs = ["Kaveri Interiors", "Marina Homes", "Walk-in Customer"]
	t0 = time.perf_counter()
	sis = []
	for i in range(n):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": CO,
				"customer": custs[i % 3],
				"update_stock": 1,
				"items": [{"item_code": "SPK-CHAIR", "qty": 2, "rate": 6500, "warehouse": wh}],
			}
		)
		submit(si, add_days(d, 1 + i // 4))
		sis.append(si.name)
		if i % 10 == 9:
			frappe.db.commit()
	t["sales_invoice_update_stock"] = (time.perf_counter() - t0) / n

	t0 = time.perf_counter()
	for i in range(n):
		pi = frappe.get_doc(
			{
				"doctype": "Purchase Invoice",
				"company": CO,
				"supplier": "Deccan Woodcraft",
				"bill_no": f"BN-{time.time_ns()}",
				"update_stock": 1,
				"items": [{"item_code": "SPK-CHAIR", "qty": 1, "rate": 3900, "warehouse": wh}],
			}
		)
		submit(pi, add_days(d, 12 + i // 4))
		if i % 10 == 9:
			frappe.db.commit()
	t["purchase_invoice_update_stock"] = (time.perf_counter() - t0) / n

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	t0 = time.perf_counter()
	for i, name in enumerate(sis):
		pe = get_payment_entry("Sales Invoice", name)
		pe.reference_no, pe.reference_date = f"UTR{i}", add_days(d, 30)
		submit(pe, add_days(d, 30 + i // 4))
		if i % 10 == 9:
			frappe.db.commit()
	t["payment_entry"] = (time.perf_counter() - t0) / n
	frappe.db.commit()
	print("seconds per document", {k: round(v, 3) for k, v in t.items()})
	report_guards()
	print("RIV", frappe.db.count("Repost Item Valuation", {"company": CO}))


# ---------------------------------------------------------------- sentinel + uninstall
def step_sentinel():
	"""Non-demo data in the wizard company that uninstall must not touch."""
	base = "Base Company Pvt Ltd"
	ensure(
		"Customer",
		"Sentinel Customer",
		{
			"customer_name": "Sentinel Customer",
			"customer_group": "Commercial",
			"territory": "All Territories",
		},
	)
	ensure(
		"Item",
		"SENTINEL-SVC",
		{
			"item_code": "SENTINEL-SVC",
			"item_group": "Services" if frappe.db.exists("Item Group", "Services") else "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
			"gst_hsn_code": "998311",
		},
	)
	if not frappe.db.exists("Sales Invoice", {"customer": "Sentinel Customer", "docstatus": 1}):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": base,
				"customer": "Sentinel Customer",
				"items": [{"item_code": "SENTINEL-SVC", "qty": 1, "rate": 1000}],
			}
		)
		submit(si, getdate("2026-07-01"))
	frappe.db.commit()
	print(counts())


def counts():
	out = {}
	for co in ["Base Company Pvt Ltd", CO]:
		out[co] = {
			dt: frappe.db.count(dt, {"company": co})
			for dt in [
				"Sales Invoice",
				"Purchase Invoice",
				"Payment Entry",
				"GL Entry",
				"Stock Ledger Entry",
				"Payment Ledger Entry",
				"Account",
				"Warehouse",
			]
		}
	out["series"] = frappe.db.sql(
		"select name, current from tabSeries where name like 'ACC-SINV-%' or name like 'ACC-PINV-%'"
	)
	out["masters"] = {dt: frappe.db.count(dt) for dt in ["Customer", "Supplier", "Item", "Address"]}
	return out


def step_uninstall():
	from erpnext.setup.demo import create_transaction_deletion_record

	print("before", json.dumps(counts(), default=str))
	frappe.db.set_single_value("Global Defaults", "default_company", "Base Company Pvt Ltd")
	frappe.db.set_default("company", "Base Company Pvt Ltd")
	install_guards()
	t0 = time.perf_counter()
	create_transaction_deletion_record(CO)
	print("TDR seconds", round(time.perf_counter() - t0, 2))
	tdr = frappe.get_last_doc("Transaction Deletion Record")
	print("TDR", tdr.name, tdr.status, (tdr.error_log or "")[:500])
	print("after TDR", json.dumps(counts(), default=str))
	frappe.db.commit()
	report_guards()


def step_delete_company():
	t0 = time.perf_counter()
	try:
		frappe.delete_doc("Company", CO, ignore_permissions=True)
		frappe.db.commit()
		print("company deleted", round(time.perf_counter() - t0, 2))
	except Exception as e:
		frappe.db.rollback()
		print("company delete failed:", type(e).__name__, str(e)[:800])
	print(json.dumps(counts(), default=str))


def run(step, **kw):
	frappe.flags.mute_emails = True
	globals()[f"step_{step}"](**kw)


def step_finish_delete():
	print("TDR status", frappe.get_all("Transaction Deletion Record", fields=["name", "status", "docstatus"]))
	for a in frappe.get_all(
		"Dynamic Link", {"link_doctype": "Company", "link_name": CO, "parenttype": "Address"}, pluck="parent"
	):
		frappe.delete_doc("Address", a, ignore_permissions=True)
		print("deleted address", a)
	step_delete_company()
	left = {}
	for dt in [
		"Item Tax Template",
		"Sales Taxes and Charges Template",
		"Purchase Taxes and Charges Template",
		"Account",
		"Cost Center",
		"Warehouse",
		"Mode of Payment Account",
		"Item Default",
		"Bin",
		"Repost Item Valuation",
		"Tax Withholding Account",
		"Party Account",
	]:
		meta = frappe.get_meta(dt)
		if meta.has_field("company"):
			n = frappe.db.count(dt, {"company": CO})
			if n:
				left[dt] = n
	left["GST Settings accounts"] = len(
		[r for r in frappe.get_single("GST Settings").gst_accounts if r.company == CO]
	)
	left["Global default company"] = frappe.db.get_default("company")
	left["Deleted Document rows"] = frappe.db.count("Deleted Document")
	left["Series"] = frappe.db.sql(
		"select name, current from tabSeries where name like 'SINV-%%' or name like 'PINV-%%' or name like 'ACC-PAY-%%'"
	)
	print("leftovers", json.dumps(left, default=str))


def step_cleanup():
	for dt, names in [
		("Customer", ["Kaveri Interiors", "Marina Homes", "Walk-in Customer"]),
		("Supplier", ["Deccan Woodcraft"]),
		("Item", ["SPK-SOFA-3", "SPK-CHAIR"]),
		("Item Group", ["Spike Furniture"]),
	]:
		for n in names:
			if not frappe.db.exists(dt, n):
				continue
			frappe.delete_doc(dt, n, ignore_permissions=True)
			print("deleted", dt, n)
	frappe.db.commit()
	print(counts())
