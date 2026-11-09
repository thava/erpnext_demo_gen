"""verify: check that an installed demo is internally consistent (M-10, design 5.13).

Each check returns a Check(name, ok, detail). The checks use ERPNext's own
reports where they exist (receivable and payable aging, stock balance, gross
profit), so a passing verify also means those screens work on the data.
"""

from dataclasses import dataclass

import frappe
from frappe.utils import flt, getdate

from demo_data.registry import DONE_STATES, Run

TOLERANCE = 1.0  # rupees; rounding across hundreds of documents

# documents a run creates itself; anything else of these types in the demo company is unregistered
REGISTERED_DOCTYPES = (
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Material Request",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
	"Payment Entry",
	"Journal Entry",
)

# list views that should show data (screen coverage)
COVERAGE = {
	"Quotation": [("status", "Open"), ("status", "Ordered")],
	"Sales Order": [("status", "Completed"), ("status", "To Deliver and Bill")],
	"Delivery Note": [("docstatus", 1)],
	"Sales Invoice": [
		("status", "Paid"),
		("status", "Overdue"),
		("is_return", 1),
		("docstatus", 0),
		("docstatus", 2),
	],
	"Material Request": [("docstatus", 1)],
	"Purchase Order": [("status", "Completed")],
	"Purchase Receipt": [("docstatus", 1)],
	"Purchase Invoice": [("status", "Paid")],
	"Payment Entry": [("payment_type", "Receive"), ("payment_type", "Pay")],
}


@dataclass
class Check:
	name: str
	ok: bool
	detail: str = ""


def verify_run(run: Run) -> list[Check]:
	company = run.doc.company
	if not (company and frappe.db.exists("Company", company)):
		return [Check("company exists", False, f"{company!r} not found")]
	from demo_data.setup.company import date_range

	start, end = date_range(getdate(run.params.end_date), run.params.months)
	ctx = frappe._dict(run=run, company=company, start=start, end=end)
	checks = []
	for fn in (
		check_trial_balance,
		check_receivables,
		check_payables,
		check_stock,
		check_no_pending_reposts,
		check_tax_rows,
		check_registry,
		check_coverage,
		check_reports,
		check_banking,
	):
		try:
			result = fn(ctx)
		except Exception as e:
			result = Check(
				fn.__name__.removeprefix("check_").replace("_", " "), False, f"{type(e).__name__}: {e}"
			)
		checks.extend(result if isinstance(result, list) else [result])
	return checks


def _sum(sql: str, *args) -> float:
	return flt(frappe.db.sql(sql, args)[0][0])


# ---------------------------------------------------------------- ledgers
def check_trial_balance(ctx) -> Check:
	diff = _sum(
		"select sum(debit) - sum(credit) from `tabGL Entry` where company=%s and is_cancelled=0", ctx.company
	)
	return Check("trial balance balances", abs(diff) < TOLERANCE, f"debit - credit = {diff:,.2f}")


def _aging(ctx, party_type: str) -> Check:
	if party_type == "Customer":
		from erpnext.accounts.report.accounts_receivable.accounts_receivable import execute
	else:
		from erpnext.accounts.report.accounts_payable.accounts_payable import execute
	filters = frappe._dict(
		company=ctx.company,
		report_date=ctx.end,
		ageing_based_on="Due Date",
		calculate_ageing_with="Report Date",
		range="30, 60, 90, 120",
	)
	rows = [r for r in execute(filters)[1] if isinstance(r, dict)]
	report = sum(flt(r.get("outstanding")) for r in rows)
	doctype = "Sales Invoice" if party_type == "Customer" else "Purchase Invoice"
	invoices = _sum(
		f"select sum(outstanding_amount) from `tab{doctype}` where company=%s and docstatus=1", ctx.company
	)
	ledger = _sum(
		"""select sum(amount) from `tabPayment Ledger Entry`
		where company=%s and party_type=%s and delinked=0""",
		ctx.company,
		party_type,
	)
	ok = abs(report - invoices) < TOLERANCE and abs(invoices - ledger) < TOLERANCE
	label = "receivable" if party_type == "Customer" else "payable"
	return Check(
		f"{label} aging matches outstanding",
		ok,
		f"report {report:,.2f}, invoices {invoices:,.2f}, payment ledger {ledger:,.2f}",
	)


def check_receivables(ctx) -> Check:
	return _aging(ctx, "Customer")


def check_payables(ctx) -> Check:
	return _aging(ctx, "Supplier")


def check_stock(ctx) -> list[Check]:
	negative = _sum(
		"""select count(*) from `tabStock Ledger Entry`
		where company=%s and is_cancelled=0 and qty_after_transaction < 0""",
		ctx.company,
	)
	mismatched = frappe.db.sql(
		"""select b.item_code, b.warehouse, b.actual_qty,
			(select sle.qty_after_transaction from `tabStock Ledger Entry` sle
			 where sle.item_code=b.item_code and sle.warehouse=b.warehouse and sle.is_cancelled=0
			 order by sle.posting_datetime desc, sle.creation desc limit 1) as ledger_qty
		from tabBin b join tabWarehouse w on w.name=b.warehouse
		where w.company=%s
		having abs(ifnull(ledger_qty, 0) - b.actual_qty) > 0.001""",
		(ctx.company,),
	)
	bins = _sum(
		"select sum(b.stock_value) from tabBin b join tabWarehouse w on w.name=b.warehouse where w.company=%s",
		ctx.company,
	)
	accounts = frappe.get_all(
		"Account", {"company": ctx.company, "account_type": "Stock", "is_group": 0}, pluck="name"
	)
	gl = _sum(
		"select sum(debit-credit) from `tabGL Entry` where account in %s and is_cancelled=0",
		tuple(accounts) or ("",),
	)
	return [
		Check("no negative stock", not negative, f"{int(negative)} ledger rows below zero"),
		Check(
			"bin quantities match the stock ledger",
			not mismatched,
			", ".join(f"{i} @ {w}" for i, w, *_ in mismatched[:5]) or "all match",
		),
		Check(
			"stock value matches the stock account",
			abs(bins - gl) < TOLERANCE,
			f"bins {bins:,.2f}, GL {gl:,.2f}",
		),
	]


def check_no_pending_reposts(ctx) -> Check:
	n = frappe.db.count(
		"Repost Item Valuation",
		{"company": ctx.company, "status": ["in", ("Queued", "In Progress", "Failed")]},
	)
	return Check("no pending stock reposts", not n, f"{n} queued or failed")


def check_tax_rows(ctx) -> Check:
	"""GST rows match the company's registration.

	Registered (F-16): every submitted sale and every purchase from a GST-registered
	supplier carries GST rows, except zero-rated SEZ and export supplies made without
	GST (under a bond). Unregistered (--no-gst): sales carry none, and those
	purchases carry GST as part of cost ("Valuation and Total"), since no credit can
	be claimed.
	"""
	registered = ctx.run.params.get("gst", "registered") == "registered"
	wrong = []
	sales_rows = "exists" if registered else "not exists"
	# SEZ and export supplies are zero-rated: without "export with GST" (supply under a
	# bond, LUT) they rightly carry no GST rows, so the registered check skips them
	zero_rated = (
		"and not (d.gst_category in ('SEZ', 'Overseas') and ifnull(d.is_export_with_gst, 0) = 0)" if registered else ""
	)
	for doctype in ("Quotation", "Sales Order", "Sales Invoice"):
		wrong += frappe.db.sql_list(
			f"""select d.name from `tab{doctype}` d where d.company=%s and d.docstatus=1 {zero_rated}
			and not {sales_rows} (select 1 from `tabSales Taxes and Charges` t where t.parent=d.name)""",
			(ctx.company,),
		)
	cost_only = "" if registered else "and t.category = 'Valuation and Total'"
	for doctype in ("Purchase Order", "Purchase Invoice"):
		wrong += frappe.db.sql_list(
			f"""select d.name from `tab{doctype}` d join tabSupplier s on s.name=d.supplier
			where d.company=%s and d.docstatus=1 and s.gst_category != 'Unregistered'
			and not exists (select 1 from `tabPurchase Taxes and Charges` t
				where t.parent=d.name {cost_only})""",
			(ctx.company,),
		)
	if wrong and ctx.run.params.get("use_wizard_company"):
		# the wizard company also holds the user's own documents; judge only the run's
		ours = set(
			frappe.get_all(
				"Demo Data Record", filters={"run": ctx.run.name, "ref_name": ["in", wrong]}, pluck="ref_name"
			)
		)
		wrong = [name for name in wrong if name in ours]
	if registered:
		return Check("taxable documents have GST rows", not wrong, ", ".join(wrong[:5]) or "all present")
	return Check(
		"no GST on sales, purchase GST in cost (unregistered)",
		not wrong,
		", ".join(wrong[:5]) or "all as expected",
	)


def check_registry(ctx) -> list[Check]:
	records = frappe.get_all(
		"Demo Data Record",
		filters={"run": ctx.run.name, "state": ["in", (*DONE_STATES, "Cancelled")]},
		fields=["ref_doctype", "ref_name"],
	)
	registered = {(r.ref_doctype, r.ref_name) for r in records}
	missing = [f"{dt} {name}" for dt, name in registered if not frappe.db.exists(dt, name)]
	unregistered = []
	for doctype in REGISTERED_DOCTYPES:
		for name in frappe.get_all(doctype, filters={"company": ctx.company}, pluck="name"):
			if (doctype, name) not in registered:
				unregistered.append(f"{doctype} {name}")
	gaps = ctx.run.gaps()
	checks = [
		Check(
			"registered documents exist", not missing, ", ".join(missing[:5]) or f"{len(registered)} checked"
		),
		Check("no failed or skipped plan steps", not gaps, ", ".join(gaps[:5]) or "none"),
	]
	if not ctx.run.params.get("use_wizard_company"):  # the wizard company also holds the user's own documents
		checks.insert(
			1,
			Check(
				"demo company has no unregistered documents",
				not unregistered,
				", ".join(unregistered[:5]) or "none",
			),
		)
	return checks


# ---------------------------------------------------------------- screens
def check_coverage(ctx) -> Check:
	empty = []
	for doctype, conditions in COVERAGE.items():
		for field, value in conditions:
			if not frappe.db.exists(doctype, {"company": ctx.company, field: value}):
				empty.append(f"{doctype} {field}={value}")
	return Check("list views have data in every main state", not empty, ", ".join(empty) or "all present")


def check_reports(ctx) -> Check:
	from erpnext.accounts.report.gross_profit.gross_profit import execute as gross_profit
	from erpnext.stock.report.stock_balance.stock_balance import execute as stock_balance

	period = frappe._dict(company=ctx.company, from_date=ctx.start, to_date=ctx.end)
	results = {
		"Stock Balance": len(stock_balance(frappe._dict(period))[1]),
		"Gross Profit": len(gross_profit(frappe._dict(period, group_by="Invoice"))[1]),
	}
	empty = [name for name, n in results.items() if not n]
	return Check(
		"standard reports return rows", not empty, ", ".join(f"{k}: {v}" for k, v in results.items())
	)


def check_banking(ctx) -> list[Check]:
	"""Payments use every mode the pack plans, through the demo's own bank accounts; bank
	clearance matches a reconciliation done up to the end of the previous month; and the
	weekly transfers leave only the latest week's receipts in the collection account and
	the cash box."""
	from datetime import timedelta

	from erpnext.accounts.report.bank_reconciliation_statement.bank_reconciliation_statement import (
		execute as bank_reconciliation,
	)
	from erpnext.accounts.utils import get_balance_on

	from demo_data.packs import load_pack
	from demo_data.planner.transactions import planned_mode_names, reconciled_until

	banking = ctx.run.params.get("banking") or {}
	accounts = banking.get("accounts")
	if not accounts:
		return []  # runs from before the two-bank setup
	payments = frappe.db.sql(
		"""select pe.name, pe.payment_type, pe.mode_of_payment, pe.bank_account, pe.paid_from,
			pe.paid_to, pe.reference_no, pe.posting_date, pe.clearance_date
		from `tabPayment Entry` pe join `tabDemo Data Record` r
			on r.ref_doctype = 'Payment Entry' and r.ref_name = pe.name and r.run = %s
		where pe.docstatus = 1""",
		ctx.run.name,
		as_dict=True,
	)
	pack = load_pack(ctx.run.params.pack)
	planned = planned_mode_names(pack["banking"])
	parties = [p for p in payments if p.payment_type != "Internal Transfer"]
	used = {p.mode_of_payment for p in parties}
	modes = Check(
		"payments use every planned mode",
		planned <= used,
		", ".join(f"{m}: {sum(p.mode_of_payment == m for p in parties)}" for m in sorted(used))
		+ (f"; never used: {', '.join(sorted(planned - used))}" if planned - used else ""),
	)

	ours = {a["bank_account"]: a["ledger"] for a in accounts.values()}
	reconciled = reconciled_until(getdate(ctx.end))
	bank = [p for p in parties if p.mode_of_payment != "Cash"]
	wrong = [
		p.name
		for p in bank
		if p.bank_account not in ours
		or ours[p.bank_account] not in (p.paid_from, p.paid_to)
		or not p.reference_no
		or (p.clearance_date and not (p.posting_date <= p.clearance_date <= reconciled))
		or (not p.clearance_date and p.posting_date < reconciled - timedelta(days=10))
	]
	cleared = sum(1 for p in bank if p.clearance_date)
	consistent = Check(
		"bank payments use the demo bank accounts and clear consistently",
		not wrong and cleared and cleared < len(bank),
		", ".join(wrong[:5]) or f"{cleared} cleared, {len(bank) - cleared} not yet (reconciled up to {reconciled})",
	)

	# weekly transfers: what is left is only what came in since the last one
	transfers = [p for p in payments if p.payment_type == "Internal Transfer"]
	cash = frappe.get_cached_value("Company", ctx.company, "default_cash_account")
	left = []
	for label, ledger in (("collection", accounts["collection"]["ledger"]), ("cash", cash)):
		last = max((p.posting_date for p in transfers if p.paid_from == ledger), default=None)
		balance = get_balance_on(account=ledger, date=ctx.end, company=ctx.company)
		since = frappe.db.sql(
			"""select coalesce(sum(debit - credit), 0) from `tabGL Entry`
			where account = %s and is_cancelled = 0 and posting_date >= %s and posting_date <= %s
			and not (voucher_type = 'Payment Entry' and voucher_no in %s)""",
			(ledger, last or ctx.start, ctx.end, tuple(p.name for p in transfers) or ("",)),
		)[0][0]
		if not last or abs(balance - since) > 1:
			left.append(f"{label}: balance {balance:,.2f}, received since last transfer {since:,.2f}")
	swept = Check(
		"collection account and cash moved to the main account weekly",
		not left,
		"; ".join(left) or f"{len(transfers)} transfers",
	)

	rows = {
		role: len(bank_reconciliation(frappe._dict(company=ctx.company, account=a["ledger"], report_date=ctx.end))[1])
		for role, a in accounts.items()
	}
	report = Check(
		"bank reconciliation statements have rows",
		all(rows.values()),
		", ".join(f"{role}: {n} rows" for role, n in rows.items()),
	)
	return [modes, consistent, swept, report]
