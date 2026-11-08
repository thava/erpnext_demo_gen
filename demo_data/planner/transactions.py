"""Transaction plan: funding, purchases and sales in date order (design 5.5, M-7).

Approach:
1. Spread sales over the range by the pack's seasonality: showroom invoices
   (b2c, stock leaves with the invoice) and dealer orders (b2b: quotation, sales
   order, delivery note, invoice), plus lost quotations.
2. Mark state coverage: drafts near the end, cancellations, returns, partial
   deliveries, and payment outcomes (on time, late, partly paid, open/overdue).
3. Walk the calendar with a stock ledger: receipts land before same-day sales,
   a shortfall triggers an emergency purchase dated before the sale, and items
   below their reorder level get a material request and purchase order. Stock
   therefore never goes negative and nothing is back-dated (A-9).
4. Simulate the bank balance and raise the opening term loan if needed, so the
   bank never goes negative.
5. Sort everything by (date, stage, creation order) and give each document a
   strictly increasing posting time within its day.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from demo_data.planner import Plan, ref
from demo_data.planner.masters import TERM_DAYS, weighted

# order of stages within one day
STAGE = {
	"funding": 0,
	"material_request": 10,
	"purchase_order": 20,
	"purchase_receipt": 30,
	"purchase_invoice": 40,
	"supplier_payment": 50,
	"quotation": 60,
	"sales_order": 70,
	"delivery_note": 80,
	"sales_invoice": 90,
	"customer_payment": 100,
	"sales_return": 110,
	"refund": 120,
}
BANK_FLOOR = 100_000
LOST_QUOTATION_SHARE = 0.25
PARTIAL_DELIVERY_SHARE = 0.12
SPLIT_LATE_PAYMENT_SHARE = 0.4
SUPPLIER_TERMS_DAYS = 30
SUPPLIER_ON_TIME_SHARE = 0.85
REORDER_WEEKDAY = 0  # Monday


@dataclass
class Event:
	date: date
	stage: str
	key: str
	doctype: str
	builder: str
	params: dict
	order: int | None = None  # creation order; set by Timeline.add
	after: int = 0  # 1 = immediately after the event with the same (date, stage, order), e.g. a cancel
	bank: float = 0.0  # effect on the bank balance, for the cash simulation
	consumes: list = field(default_factory=list)  # [(item_key, qty)] leaving stock on this date

	def sort_key(self):
		return (self.date, STAGE[self.stage], self.order, self.after)


@dataclass
class ItemInfo:
	key: str
	sell: float
	buy: float
	gst: float
	reorder_min: int
	reorder_max: int
	supplier: str | None


class Timeline:
	def __init__(self):
		self.events: list[Event] = []
		self.counters: dict[str, int] = defaultdict(int)

	def next_key(self, prefix: str) -> str:
		self.counters[prefix] += 1
		return f"T:{prefix}:{self.counters[prefix]:06d}"

	def add(self, event: Event) -> Event:
		if event.order is None:
			event.order = len(self.events) + 1
		self.events.append(event)
		return event


# ---------------------------------------------------------------- helpers
def days_between(a: date, b: date) -> int:
	return (b - a).days


def clamp(d: date, low: date, high: date) -> date:
	return max(low, min(d, high))


def pareto_weights(rng, n: int, alpha: float) -> list[float]:
	"""A few heavy hitters and a long tail, in random order."""
	ranks = list(range(1, n + 1))
	rng.shuffle(ranks)
	return [1 / (r**alpha) for r in ranks]


def month_starts(start: date, end: date) -> list[date]:
	months, d = [], date(start.year, start.month, 1)
	while d <= end:
		months.append(d)
		d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
	return months


def spread_over_months(
	total: int, start: date, end: date, seasonality: list[float]
) -> list[tuple[date, date, int]]:
	"""[(first_day, last_day, count)] per month in range, weighted by seasonality (index 0 = April)."""
	spans = []
	for m in month_starts(start, end):
		next_m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
		first, last = max(m, start), min(next_m - timedelta(days=1), end)
		share = (days_between(first, last) + 1) / (days_between(m, next_m))
		spans.append((first, last, seasonality[(m.month - 4) % 12] * share))
	weight_total = sum(w for _, _, w in spans) or 1
	exact = [total * w / weight_total for _, _, w in spans]
	counts = [int(x) for x in exact]
	for i in sorted(range(len(spans)), key=lambda i: exact[i] - counts[i], reverse=True)[
		: total - sum(counts)
	]:
		counts[i] += 1
	return [(f, last, c) for (f, last, _), c in zip(spans, counts, strict=True)]


def random_dates(rng, total, start, end, seasonality) -> list[date]:
	out = []
	for first, last, count in spread_over_months(total, start, end, seasonality):
		out += [first + timedelta(days=rng.randint(0, days_between(first, last))) for _ in range(count)]
	return sorted(out)


def with_tax(amount: float, gst: float) -> float:
	return amount * (1 + gst / 100)


# ---------------------------------------------------------------- entry point
def plan_transactions(plan: Plan):
	ctx = plan.ctx
	items = read_items(plan)
	customers = [d for d in plan.docs if d.doctype == "Customer"]
	terms_days = {d.key: d.params["days"] for d in plan.docs if d.doctype == "Payment Terms Template"}
	tl = Timeline()

	plan_sales(ctx, tl, items, customers, terms_days)
	fit_reorder_levels(plan, tl, items)
	plan_stock_and_purchases(ctx, tl, items)
	plan_funding(ctx, tl)
	emit(plan, tl)


def read_items(plan: Plan) -> dict[str, ItemInfo]:
	prices = {
		(d.params["list"], d.params["item"]["$ref"]): d.params["rate"]
		for d in plan.docs
		if d.doctype == "Item Price"
	}
	items = {}
	for d in plan.docs:
		if d.doctype == "Item":
			p = d.params
			items[d.key] = ItemInfo(
				key=d.key,
				sell=prices[("selling", d.key)],
				buy=prices[("buying", d.key)],
				gst=p["gst_rate"],
				reorder_min=p["reorder"]["min"],
				reorder_max=p["reorder"]["max"],
				supplier=p["suppliers"][0]["$ref"] if p["suppliers"] else None,
			)
	return items


# ---------------------------------------------------------------- sales
def plan_sales(ctx, tl: Timeline, items: dict[str, ItemInfo], customers, terms_days):
	pack = ctx.pack
	behavior = pack["behavior"]
	seasonality = behavior["seasonality"]["monthly_index"]
	alpha = behavior["customer_skew"].get("alpha", 1.2)
	rng = ctx.rng("sales")
	item_keys = sorted(items)
	item_weights = pareto_weights(ctx.rng("item-popularity"), len(item_keys), 1.0)

	total = ctx.size["sales_invoices"]
	channels = pack["channels"]
	for channel in channels:
		count = round(total * channel["share"])
		members = [c for c in customers if c.params.get("channel") == channel["id"]]
		if not members:
			continue
		weights = pareto_weights(ctx.rng(f"customer-skew:{channel['id']}"), len(members), alpha)
		walk_in = next((c for c in members if c.key == "M:customer:walk-in"), None)
		named = [c for c in members if c is not walk_in]
		named_weights = [w for c, w in zip(members, weights, strict=True) if c is not walk_in]
		dates = random_dates(rng, count, ctx.start_date, ctx.end_date, seasonality)

		def pick_customer(walk_in=walk_in, named=named, named_weights=named_weights):
			if walk_in and (not named or rng.random() < 0.5):
				return walk_in
			return rng.choices(named, weights=named_weights)[0]

		def pick_lines(n, qty_range):
			chosen = []
			while len(chosen) < min(n, len(item_keys)):
				k = rng.choices(item_keys, weights=item_weights)[0]
				if k not in chosen:  # never repeat an item in one document (A-9)
					chosen.append(k)
			lines = []
			for k in chosen:
				low, high = qty_range
				if items[k].sell > 40000:
					high = max(low, high // 2)
				lines.append((k, rng.randint(low, high)))
			return lines

		if "sales_order" in channel["flow"]:
			plan_order_flow(ctx, tl, rng, channel, dates, pick_customer, pick_lines, items, terms_days)
		else:
			plan_counter_sales(ctx, tl, rng, channel, dates, pick_customer, pick_lines, items, terms_days)


def credit_days(rng, channel, customer, terms_days) -> int:
	if customer.params.get("payment_terms"):
		return terms_days[customer.params["payment_terms"]["$ref"]]
	term = weighted(rng, channel["payment"])
	return TERM_DAYS.get(term, 0)


def amount_of(lines, items, rate_field="sell", gst=True) -> float:
	return sum(with_tax(getattr(items[k], rate_field) * q, items[k].gst if gst else 0) for k, q in lines)


def plan_counter_sales(ctx, tl, rng, channel, dates, pick_customer, pick_lines, items, terms_days):
	"""Showroom: invoice with stock update, paid at the counter or on credit."""
	rates = ctx.pack["behavior"]["rates"]
	sales = []
	for d in dates:
		customer = pick_customer()
		low, high = channel.get("lines", [1, 2])
		lines = pick_lines(
			low if rng.random() < 0.7 else rng.randint(low, high), tuple(channel.get("quantity", [1, 2]))
		)
		days = 0 if customer.key == "M:customer:walk-in" else credit_days(rng, channel, customer, terms_days)
		sales.append({"date": d, "customer": customer, "lines": lines, "days": days})

	n = len(sales)
	recent = [s for s in sales if days_between(s["date"], ctx.end_date) <= 30]
	for s in rng.sample(recent, min(len(recent), max(1, round(rates["left_in_draft"] * n)))):
		s["draft"] = True
	# Cancellations happen on dealer invoices (plan_delivery): cancelling a stock-moving
	# showroom invoice queues a stock repost that the scheduler then races (F-34).
	others = [s for s in sales if not s.get("draft")]
	returnable = [s for s in others if not s.get("cancel") and days_between(s["date"], ctx.end_date) >= 3]
	for s in rng.sample(returnable, min(len(returnable), max(1, round(rates["returns"] * n)))):
		s["return"] = True

	for s in sales:
		key = tl.next_key("SI")
		lines = [{"item": ref(k), "qty": q, "rate": items[k].sell} for k, q in s["lines"]]
		amount = amount_of(s["lines"], items, gst=ctx.sales_gst)
		draft = bool(s.get("draft"))
		tl.add(
			Event(
				s["date"],
				"sales_invoice",
				key,
				"Sales Invoice",
				"counter_sales_invoice",
				{
					"customer": ref(s["customer"].key),
					"lines": lines,
					"credit_days": s["days"],
					"draft": draft,
				},
				consumes=[] if draft else s["lines"],
			)
		)
		if draft:
			continue
		paid_now = plan_customer_payment(ctx, tl, rng, key, s["date"], amount, s["days"], cash=not s["days"])
		if s.get("return"):
			k, _ = s["lines"][0]
			rdate = min(s["date"] + timedelta(days=rng.randint(3, 20)), ctx.end_date)
			rkey = tl.next_key("SRET")
			tl.add(
				Event(
					rdate,
					"sales_return",
					rkey,
					"Sales Invoice",
					"sales_return",
					{"against": ref(key), "item": ref(k), "qty": 1},
				)
			)
			if paid_now:
				tl.add(
					Event(
						rdate,
						"refund",
						tl.next_key("PE"),
						"Payment Entry",
						"refund",
						{"credit_note": ref(rkey), "cash": True},
					)
				)


def plan_order_flow(ctx, tl, rng, channel, dates, pick_customer, pick_lines, items, terms_days):
	"""Dealers and projects: [quotation ->] sales order -> delivery note(s) -> invoice(s) -> payment."""
	start, end = ctx.start_date, ctx.end_date
	with_quotation = "quotation" in channel["flow"]
	qty_range = tuple(channel.get("quantity", [2, 8]))
	min_lines, max_lines = channel.get("lines", [2, 4])
	for so_date in dates:
		customer = pick_customer()
		lines = pick_lines(rng.randint(min_lines, max_lines), qty_range)
		days = credit_days(rng, channel, customer, terms_days)
		dn_date = so_date + timedelta(days=rng.randint(2, 10))
		so_params = {"delivery_date": min(dn_date, end + timedelta(days=15))}
		order_lines = [{"item": ref(k), "qty": q, "rate": items[k].sell} for k, q in lines]
		if with_quotation:
			q_date = clamp(so_date - timedelta(days=rng.randint(1, 7)), start, so_date)
			q_key = tl.next_key("QTN")
			tl.add(
				Event(
					q_date,
					"quotation",
					q_key,
					"Quotation",
					"quotation",
					{"customer": ref(customer.key), "lines": order_lines},
				)
			)
			so_params["quotation"] = ref(q_key)
		else:
			so_params.update(customer=ref(customer.key), lines=order_lines)
		so_key = tl.next_key("SO")
		tl.add(Event(so_date, "sales_order", so_key, "Sales Order", "sales_order", so_params))
		if dn_date > end:
			continue  # open order, still to deliver
		partial = rng.random() < PARTIAL_DELIVERY_SHARE
		first = [(k, max(1, q // 2)) for k, q in lines] if partial else lines
		plan_delivery(ctx, tl, rng, so_key, dn_date, first, 0.5 if partial else None, items, days)
		# half the partial deliveries stay open, so "partly delivered" orders show up
		if partial and rng.random() < 0.5:
			second_date = dn_date + timedelta(days=rng.randint(7, 20))
			if second_date <= end:
				rest = [(k, q - fq) for (k, q), (_, fq) in zip(lines, first, strict=True) if q - fq > 0]
				plan_delivery(ctx, tl, rng, so_key, second_date, rest, None, items, days)

	# quotations that never became orders
	lost = round(len(dates) * LOST_QUOTATION_SHARE) if with_quotation else 0
	for q_date in random_dates(rng, lost, start, end, ctx.pack["behavior"]["seasonality"]["monthly_index"]):
		customer = pick_customer()
		lines = pick_lines(rng.randint(1, max_lines), qty_range)
		tl.add(
			Event(
				q_date,
				"quotation",
				tl.next_key("QTN"),
				"Quotation",
				"quotation",
				{
					"customer": ref(customer.key),
					"lines": [{"item": ref(k), "qty": q, "rate": items[k].sell} for k, q in lines],
				},
			)
		)


def plan_delivery(ctx, tl, rng, so_key, dn_date, lines, fraction, items, days):
	dn_key = tl.next_key("DN")
	tl.add(
		Event(
			dn_date,
			"delivery_note",
			dn_key,
			"Delivery Note",
			"delivery_note",
			{"sales_order": ref(so_key), "fraction": fraction},
			consumes=lines,
		)
	)
	si_key = tl.next_key("SI")
	invoice = tl.add(
		Event(
			dn_date,
			"sales_invoice",
			si_key,
			"Sales Invoice",
			"invoice_from_delivery",
			{"delivery_note": ref(dn_key), "credit_days": days},
		)
	)
	# Some invoices are raised wrongly, cancelled and re-issued from the same delivery
	# note. No stock moves, so no repost is queued. At least one per install, so the
	# cancelled state always shows.
	rate = ctx.pack["behavior"]["rates"]["cancelled"]
	if rng.random() < rate or (not tl.counters["cancelled"] and tl.counters["DN"] >= 10):
		tl.counters["cancelled"] += 1
		tl.add(
			Event(
				dn_date,
				"sales_invoice",
				f"{si_key}:cancel",
				"Sales Invoice",
				"cancel",
				{"doctype": "Sales Invoice", "doc": ref(si_key)},
				order=invoice.order,
				after=1,
			)
		)
		si_key = tl.next_key("SI")
		tl.add(
			Event(
				dn_date,
				"sales_invoice",
				si_key,
				"Sales Invoice",
				"invoice_from_delivery",
				{"delivery_note": ref(dn_key), "credit_days": days},
			)
		)
	plan_customer_payment(ctx, tl, rng, si_key, dn_date, amount_of(lines, items, gst=ctx.sales_gst), days, cash=False)


def plan_customer_payment(ctx, tl, rng, si_key, si_date, amount, days, cash) -> bool:
	"""Schedule receipts for an invoice. Returns True when paid on the spot."""
	end = ctx.end_date

	def receipt(when, fraction=None, last=True):
		if when > end:
			return
		share = fraction or 1.0
		tl.add(
			Event(
				when,
				"customer_payment",
				tl.next_key("PE"),
				"Payment Entry",
				"receive_payment",
				{"invoice": ref(si_key), "fraction": None if last else fraction, "cash": cash},
				bank=0 if cash else amount * share,
			)
		)

	if days == 0:
		receipt(si_date)
		return True
	outcome = weighted(rng, ctx.pack["behavior"]["payment_outcomes"])
	due = si_date + timedelta(days=days)
	if outcome == "on_time":
		receipt(si_date + timedelta(days=rng.randint(max(1, days // 2), days)))
	elif outcome == "late":
		if rng.random() < SPLIT_LATE_PAYMENT_SHARE:
			# part now, the rest much later or not yet: "partly paid" invoices
			first = due + timedelta(days=rng.randint(3, 15))
			receipt(first, fraction=0.5, last=False)
			if first <= end and rng.random() < 0.5:
				receipt(first + timedelta(days=rng.randint(30, 120)), fraction=0.5)
		else:
			receipt(due + timedelta(days=rng.randint(5, 60)))
	# open_overdue: never paid
	return False


# ---------------------------------------------------------------- stock and purchases
def fit_reorder_levels(plan: Plan, tl: Timeline, items: dict[str, ItemInfo]):
	"""Raise pack reorder levels to the planned demand: at least 2 weeks' sales as the
	minimum and 4 more weeks on top as the maximum. Without this, a larger size keeps
	running out between weekly purchases and is resupplied by emergency orders.
	The item masters get the same levels, so ERPNext's reorder settings match the plan.
	"""
	weeks = max(1.0, days_between(plan.ctx.start_date, plan.ctx.end_date) / 7)
	demand = defaultdict(int)
	for e in tl.events:
		for k, q in e.consumes:
			demand[k] += q
	params = {d.key: d.params for d in plan.docs if d.doctype == "Item"}
	for k, info in items.items():
		weekly = demand[k] / weeks
		info.reorder_min = max(info.reorder_min, math.ceil(2 * weekly))
		info.reorder_max = max(info.reorder_max, info.reorder_min + math.ceil(4 * weekly))
		params[k]["reorder"] = {"min": info.reorder_min, "max": info.reorder_max}


def plan_stock_and_purchases(ctx, tl: Timeline, items: dict[str, ItemInfo]):
	rng = ctx.rng("purchases")
	start, end = ctx.start_date, ctx.end_date
	on_hand = defaultdict(int)
	on_order = defaultdict(int)
	receipts = defaultdict(list)  # date -> [(item, qty)]
	consumption = defaultdict(list)
	for e in tl.events:
		if e.consumes:
			consumption[e.date].append(e)

	def buy(order_date, receipt_date, lines, with_request, track=True):
		"""One supplier's purchase: [material request ->] order -> receipt -> invoice -> payment."""
		supplier = items[lines[0][0]].supplier
		po_params = {
			"supplier": ref(supplier),
			"lines": [{"item": ref(k), "qty": q, "rate": items[k].buy} for k, q in lines],
			"schedule_date": receipt_date,
		}
		if with_request:
			mr_key = tl.next_key("MR")
			tl.add(
				Event(
					order_date,
					"material_request",
					mr_key,
					"Material Request",
					"material_request",
					{"lines": po_params["lines"], "schedule_date": receipt_date},
				)
			)
			po_params["material_request"] = ref(mr_key)
		po_key = tl.next_key("PO")
		tl.add(Event(order_date, "purchase_order", po_key, "Purchase Order", "purchase_order", po_params))
		if receipt_date > end:
			return  # still on order at the end of the range
		pr_key = tl.next_key("PR")
		tl.add(
			Event(
				receipt_date,
				"purchase_receipt",
				pr_key,
				"Purchase Receipt",
				"purchase_receipt",
				{"purchase_order": ref(po_key)},
			)
		)
		pi_key = tl.next_key("PI")
		tl.add(
			Event(
				receipt_date,
				"purchase_invoice",
				pi_key,
				"Purchase Invoice",
				"purchase_invoice",
				{"purchase_receipt": ref(pr_key), "bill_no": f"INV/{receipt_date.year % 100}/{pi_key[-5:]}"},
			)
		)
		total = sum(with_tax(items[k].buy * q, items[k].gst) for k, q in lines)
		due = receipt_date + timedelta(days=SUPPLIER_TERMS_DAYS)
		pay = (
			receipt_date + timedelta(days=rng.randint(SUPPLIER_TERMS_DAYS // 2, SUPPLIER_TERMS_DAYS))
			if rng.random() < SUPPLIER_ON_TIME_SHARE
			else due + timedelta(days=rng.randint(5, 30))
		)
		if pay <= end:
			tl.add(
				Event(
					pay,
					"supplier_payment",
					tl.next_key("PE"),
					"Payment Entry",
					"pay_supplier",
					{"invoice": ref(pi_key)},
					bank=-total,
				)
			)
		if track:
			for k, q in lines:
				receipts[receipt_date].append((k, q))
				on_order[k] += q

	def by_supplier(lines):
		groups = defaultdict(list)
		for k, q in lines:
			groups[items[k].supplier].append((k, q))
		return [g for s, g in sorted(groups.items(), key=lambda kv: kv[0] or "") if s]

	# opening stock on the first day: midway between the reorder levels
	opening = [(k, (i.reorder_min + i.reorder_max + 1) // 2) for k, i in sorted(items.items())]
	for group in by_supplier(opening):
		buy(start, start, group, with_request=False)

	day = start
	while day <= end:
		for k, q in receipts.pop(day, []):
			on_hand[k] += q
			on_order[k] -= q
		emergency = []
		for e in sorted(consumption.get(day, []), key=Event.sort_key):
			for k, q in e.consumes:
				if on_hand[k] < q:
					need = q - on_hand[k] + items[k].reorder_min
					emergency.append((k, need))
					on_hand[k] += need  # received earlier the same day (receipts sort before sales)
				on_hand[k] -= q
		for group in by_supplier(merge_lines(emergency)):
			# already added to on_hand above, so not tracked as a future receipt
			buy(
				max(start, day - timedelta(days=rng.randint(3, 7))),
				day,
				group,
				with_request=False,
				track=False,
			)

		reorder = [
			(k, i.reorder_max - on_hand[k] - on_order[k])
			for k, i in sorted(items.items())
			if on_hand[k] + on_order[k] <= i.reorder_min and i.reorder_max > on_hand[k] + on_order[k]
		]
		# buyers review stock once a week; shortfalls in between get emergency purchases above
		order_day = day + timedelta(days=1)
		if reorder and day.weekday() == REORDER_WEEKDAY and order_day <= end:
			for group in by_supplier(reorder):
				buy(order_day, order_day + timedelta(days=rng.randint(3, 7)), group, with_request=True)
		day += timedelta(days=1)


def merge_lines(lines):
	merged = defaultdict(int)
	for k, q in lines:
		merged[k] += q
	return sorted(merged.items())


# ---------------------------------------------------------------- funding
def plan_funding(ctx, tl: Timeline):
	"""Owner's capital and a term loan on day one, large enough to keep the bank positive."""
	funding = ctx.pack["company"].get("funding") or {}
	capital = funding.get("share_capital", 0)
	loan = funding.get("term_loan", 0)
	balance = lowest = capital + loan
	for e in sorted(tl.events, key=Event.sort_key):
		balance += e.bank
		lowest = min(lowest, balance)
	if lowest < BANK_FLOOR:
		loan += math.ceil((BANK_FLOOR - lowest) / 100_000) * 100_000
	tl.add(
		Event(
			ctx.start_date,
			"funding",
			"T:JV:000001",
			"Journal Entry",
			"funding_entry",
			{"share_capital": capital, "term_loan": loan},
			order=0,
		)
	)


# ---------------------------------------------------------------- emit
def emit(plan: Plan, tl: Timeline):
	events = sorted(tl.events, key=Event.sort_key)
	per_day = defaultdict(int)
	for e in events:
		per_day[e.date] += 1
	seen = defaultdict(int)
	for e in events:
		n = per_day[e.date]
		step = 120 if n * 120 < 10 * 3600 else max(1, (10 * 3600) // n)
		seconds = 9 * 3600 + seen[e.date] * step
		seen[e.date] += 1
		time = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
		plan.add(e.key, e.doctype, e.builder, e.params, posting_date=e.date, posting_time=time)
