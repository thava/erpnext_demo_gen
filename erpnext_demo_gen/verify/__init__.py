"""verify: check that an installed demo is internally consistent (M-10, design 5.13).

Each check returns a Check(name, ok, detail). The checks use ERPNext's own
reports where they exist (receivable and payable aging, stock balance, gross
profit), so a passing verify also means those screens work on the data.
"""

from dataclasses import dataclass

import frappe
from frappe.utils import flt, getdate

from erpnext_demo_gen.registry import DONE_STATES, Run

TOLERANCE = 1.0  # currency units; rounding across hundreds of documents

# documents a run creates itself; anything else of these types in the demo company is unregistered
REGISTERED_DOCTYPES = (
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"Material Request",
	"Stock Entry",
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
	from erpnext_demo_gen.setup.company import date_range

	start, end = date_range(getdate(run.params.end_date), run.params.months)
	ctx = frappe._dict(run=run, company=company, start=start, end=end)
	checks = []
	for fn in (
		check_trial_balance,
		check_receivables,
		check_payables,
		check_stock,
		check_no_pending_reposts,
		check_taxes,
		check_registry,
		check_coverage,
		check_reports,
		check_banking,
		check_supplies,
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


def check_taxes(ctx) -> list[Check]:
	"""The country's tax checks, from the pack's locale (India: GST rows; US: Texas sales
	and use tax; UAE: VAT and the VAT 201 report)."""
	from erpnext_demo_gen.locales import get_locale
	from erpnext_demo_gen.packs import load_pack

	return get_locale(load_pack(ctx.run.params.pack)).tax_checks(ctx)


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

	from erpnext_demo_gen.packs import load_pack
	from erpnext_demo_gen.planner.transactions import planned_mode_names, reconciled_until

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
	from erpnext_demo_gen.locales import get_locale

	pack = load_pack(ctx.run.params.pack)
	planned = planned_mode_names(pack["banking"], get_locale(pack).counter_modes)
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


def check_supplies(ctx) -> list[Check]:
	"""Own-use supplies (design 5.15): issues are expensed, and every stocked supply at or
	below its reorder level has a purchase request or order still open. Only for runs
	that planned supplies."""
	items = frappe.db.sql_list(
		"""select ref_name from `tabDemo Data Record`
		where run = %s and ref_doctype = 'Item' and plan_key like 'M:supply:item:%%'""",
		ctx.run.name,
	)
	if not items:
		return []
	issues = frappe.db.sql(
		"""select d.item_code, d.expense_account, a.root_type, se.posting_date
		from `tabStock Entry` se join `tabStock Entry Detail` d on d.parent = se.name
		left join `tabAccount` a on a.name = d.expense_account
		where se.company = %s and se.docstatus = 1 and se.stock_entry_type = 'Material Issue'""",
		ctx.company,
		as_dict=True,
	)
	not_expensed = sorted({i.item_code for i in issues if i.root_type != "Expense"})
	expensed = Check(
		"supply issues are expensed",
		bool(issues) and not not_expensed,
		f"{len(issues)} issue lines" + (f"; not to an expense account: {not_expensed}" if not_expensed else ""),
	)
	last_issue = {}
	for i in issues:
		last_issue[i.item_code] = max(last_issue.get(i.item_code, i.posting_date), i.posting_date)
	low = frappe.db.sql(
		"""select r.parent item, r.warehouse_reorder_level level, ifnull(b.actual_qty, 0) qty
		from `tabItem Reorder` r left join `tabBin` b on b.item_code = r.parent and b.warehouse = r.warehouse
		where r.parent in %(items)s and ifnull(b.actual_qty, 0) <= r.warehouse_reorder_level""",
		{"items": items},
		as_dict=True,
	)
	unordered = []
	for row in low:
		if last_issue.get(row.item) and getdate(last_issue[row.item]) >= getdate(ctx.end):
			continue  # dropped on the last day; the reorder would come tomorrow
		pending = frappe.db.sql(
			"""select 1 from `tabMaterial Request Item` i join `tabMaterial Request` m on m.name = i.parent
			where i.item_code = %(item)s and m.docstatus = 1 and m.material_request_type = 'Purchase'
				and ifnull(i.received_qty, 0) < i.qty
			union all
			select 1 from `tabPurchase Order Item` i join `tabPurchase Order` o on o.name = i.parent
			where i.item_code = %(item)s and o.docstatus = 1 and ifnull(i.received_qty, 0) < i.qty""",
			{"item": row.item},
		)
		if not pending:
			unordered.append(f"{row.item} ({row.qty:g} <= {row.level:g})")
	reorder = Check(
		"supplies at their reorder level are on order",
		not unordered,
		f"{len(low)} at or below the level" + (f"; not on order: {unordered}" if unordered else ""),
	)
	return [expensed, reorder]
