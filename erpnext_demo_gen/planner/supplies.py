"""Own-use inventory: office and shop supplies the business keeps for itself (design 5.15, D-13).

Planned only when the pack has a `supplies` section (set in the country's base pack,
since the items, their tax data and prices are country-specific):

    masters     the supply suppliers, an item group, supply items (stock items counted
                in their own warehouse with reorder levels; non-stock consumables)
    each month  per department: a staff Material Request (type Material Issue), then a
                Stock Entry issuing it from the supplies warehouse (expensed on issue)
    reorder     when an item reaches its reorder level, a purchase Material Request the
                next day (what ERPNext's daily reorder job would raise; the job itself
                does not run during an install), then order, receipt, bill and payment
    consumables non-stock items (e.g. drinking water) ordered and billed monthly

Own random streams ("supplies-*"), so packs without supplies plan exactly as before.
"""

from collections import defaultdict
from datetime import timedelta

from erpnext_demo_gen.planner import Plan, ref

SUPPLY_TERMS_DAYS = (10, 30)  # supplies are paid within these many days of the bill


def has_supplies(pack: dict) -> bool:
	return bool(pack.get("supplies"))


def plan_supply_masters(plan: Plan):
	"""Supply suppliers, the supplies item group, supply items and their buying prices."""
	from erpnext_demo_gen.planner.masters import business_party

	ctx, pack = plan.ctx, plan.ctx.pack
	if not has_supplies(pack):
		return
	cfg, locale = pack["supplies"], ctx.locale
	rng = ctx.rng("supplies-masters")
	taken = {d.params["name"] for d in plan.docs if d.doctype in ("Customer", "Supplier")}
	for i, s in enumerate(cfg["suppliers"]):
		if s.get("out_of_state"):
			region = rng.choice([r for r in locale.regions() if r != ctx.home_state])
		else:
			region = ctx.home_state
		party = business_party(rng, locale, region, s["nouns"], taken, True, "Registered Regular")
		party["group"] = pack["parties"]["supplier_group"]
		plan.add(f"M:supply:supplier:{i + 1}", "Supplier", "supplier", party)

	group_key = f"M:item_group:{cfg['item_group']}"
	if group_key not in plan.keys:
		plan.add(group_key, "Item Group", "item_group", {"name": cfg["item_group"]})
	for entry in cfg["items"]:
		code = entry["code"]
		stock = entry.get("stock", True)
		params = {
			"code": code,
			"name": entry["name"],
			"group": ref(group_key),
			"family": "supplies",
			"uom": entry.get("uom", "Nos"),
			"cost": entry["cost"],
			"is_stock": int(stock),
			"is_sales_item": 0,
			"warehouse": cfg["warehouse"],
			"expense_account": entry.get("expense_account", cfg["expense_account"]),
			"suppliers": [ref(f"M:supply:supplier:{entry.get('supplier', 1)}")],
			**locale.item_tax(entry, pack),
		}
		if stock:
			level, qty = entry["reorder"]["level"], entry["reorder"]["qty"]
			params["reorder"] = {"min": level, "max": level + qty}
		plan.add(f"M:supply:item:{code}", "Item", "item", params)
		plan.add(
			f"M:supply:price:{code}",
			"Item Price",
			"item_price",
			{"item": ref(f"M:supply:item:{code}"), "list": "buying", "rate": entry["cost"]},
		)


def plan_supplies(ctx, tl):
	"""Monthly requests and issues, reorders at the reorder level, monthly consumables."""
	from erpnext_demo_gen.planner.transactions import Event, clamp, month_starts, payment_method, with_tax

	pack = ctx.pack
	if not has_supplies(pack):
		return
	cfg, locale = pack["supplies"], ctx.locale
	rng = ctx.rng("supplies")
	start, end = ctx.start_date, ctx.end_date
	entries = {e["code"]: e for e in cfg["items"]}
	stock = sorted(c for c, e in entries.items() if e.get("stock", True))
	consumables = sorted(c for c, e in entries.items() if not e.get("stock", True))
	tax = {c: locale.purchase_tax_rate(locale.item_tax(e, pack)) for c, e in entries.items()}

	def key(code):
		return ref(f"M:supply:item:{code}")

	def supplier_of(code):
		return ref(f"M:supply:supplier:{entries[code].get('supplier', 1)}")

	def pay(bill_key, bill_date, total):
		when = bill_date + timedelta(days=rng.randint(*SUPPLY_TERMS_DAYS))
		if when > end:
			return
		tl.add(
			Event(
				when,
				"supplier_payment",
				tl.next_key("PE"),
				"Payment Entry",
				"pay_supplier",
				{"invoice": ref(bill_key), **payment_method(ctx, "supplier", total, when)},
				bank=-total,
				amount=total,
			)
		)

	def buy_stock(order_date, lines, request: bool, opening: bool = False):
		"""[purchase request ->] order -> receipt -> bill -> payment, for one supplier's lines.
		Opening stock arrives the day it is ordered, like the trading stock's."""
		receipt = order_date if opening else order_date + timedelta(days=rng.randint(2, 5))
		po = {
			"supplier": supplier_of(lines[0][0]),
			"lines": [{"item": key(c), "qty": q, "rate": entries[c]["cost"]} for c, q in lines],
			"schedule_date": receipt,
			"warehouse": cfg["warehouse"],
		}
		if request:
			mr_key = tl.next_key("MR")
			tl.add(
				Event(
					order_date,
					"material_request",
					mr_key,
					"Material Request",
					"material_request",
					{"type": "Purchase", "lines": po["lines"], "schedule_date": receipt, "warehouse": cfg["warehouse"]},
				)
			)
			po["material_request"] = ref(mr_key)
		po_key = tl.next_key("PO")
		tl.add(Event(order_date, "purchase_order", po_key, "Purchase Order", "purchase_order", po))
		if receipt > end:
			return None
		pr_key, pi_key = tl.next_key("PR"), tl.next_key("PI")
		tl.add(Event(receipt, "purchase_receipt", pr_key, "Purchase Receipt", "purchase_receipt", {"purchase_order": ref(po_key)}))
		tl.add(
			Event(
				receipt,
				"purchase_invoice",
				pi_key,
				"Purchase Invoice",
				"purchase_invoice",
				{"purchase_receipt": ref(pr_key), "bill_no": f"SUP/{receipt:%y%m}/{pi_key[-5:]}"},
			)
		)
		pay(pi_key, receipt, sum(with_tax(entries[c]["cost"] * q, tax[c]) for c, q in lines))
		return receipt

	def by_supplier(lines):
		groups = defaultdict(list)
		for c, q in lines:
			groups[entries[c].get("supplier", 1)].append((c, q))
		return [groups[s] for s in sorted(groups)]

	# opening stock: filled up to the reorder maximum on day one
	on_hand = defaultdict(int)
	arriving = defaultdict(list)  # date -> [(code, qty)]
	on_order = set()
	opening = [(c, entries[c]["reorder"]["level"] + entries[c]["reorder"]["qty"]) for c in stock]
	for group in by_supplier(opening):
		buy_stock(start, group, request=False, opening=True)
		for c, q in group:
			on_hand[c] += q

	departments = cfg["departments"]
	months = month_starts(start, end)
	for m in months:
		# consumables: one order and bill a month, early in the month
		if consumables:
			day = clamp(m + timedelta(days=rng.randint(1, 4)), start, end)
			lines = [(c, rng.randint(*entries[c]["use_per_month"])) for c in consumables]
			for group in by_supplier(lines):
				po_key, pi_key = tl.next_key("PO"), tl.next_key("PI")
				tl.add(
					Event(
						day,
						"purchase_order",
						po_key,
						"Purchase Order",
						"purchase_order",
						{
							"supplier": supplier_of(group[0][0]),
							"lines": [{"item": key(c), "qty": q, "rate": entries[c]["cost"]} for c, q in group],
							"schedule_date": day,
						},
					)
				)
				tl.add(
					Event(
						day,
						"purchase_invoice",
						pi_key,
						"Purchase Invoice",
						"purchase_invoice_from_order",
						{"purchase_order": ref(po_key), "bill_no": f"SUP/{day:%y%m}/{pi_key[-5:]}"},
					)
				)
				pay(pi_key, day, sum(with_tax(entries[c]["cost"] * q, tax[c]) for c, q in group))

		# staff requests and issues, then reorders, in date order
		requests = []
		for dept in departments:
			day = m + timedelta(days=rng.randint(2, 20))
			if start <= day <= end:
				picks = rng.sample(stock, min(len(stock), rng.randint(2, 4)))
				requests.append((day, dept, sorted(picks)))
		for day, dept, picks in sorted(requests):
			for d in sorted(d for d in list(arriving) if d <= day):
				for c, q in arriving.pop(d):
					on_hand[c] += q
					on_order.discard(c)
			lines = []
			for c in picks:
				low, high = entries[c]["use_per_month"]
				q = min(on_hand[c], max(1, rng.randint(low, high) // len(departments)))
				if q > 0:
					lines.append((c, q))
					on_hand[c] -= q
			if not lines:
				continue
			mr_key = tl.next_key("MR")
			item_lines = [{"item": key(c), "qty": q} for c, q in lines]
			tl.add(
				Event(
					day,
					"material_request",
					mr_key,
					"Material Request",
					"material_request",
					{"type": "Material Issue", "lines": item_lines, "schedule_date": day, "warehouse": cfg["warehouse"], "department": dept},
				)
			)
			tl.add(
				Event(
					day,
					"stock_issue",
					tl.next_key("SE"),
					"Stock Entry",
					"stock_issue",
					{"material_request": ref(mr_key), "lines": item_lines},
				)
			)
			# reorder: the next morning, what the daily job would request
			due = [(c, entries[c]["reorder"]["qty"]) for c in stock if on_hand[c] <= entries[c]["reorder"]["level"] and c not in on_order]
			order_day = day + timedelta(days=1)
			if due and order_day <= end:
				for group in by_supplier(due):
					receipt = buy_stock(order_day, group, request=True)
					for c, q in group:
						on_order.add(c)
						if receipt:
							arriving[receipt].append((c, q))
