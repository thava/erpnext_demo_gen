"""Master data plan: payment terms, item groups, suppliers, items, prices, customers.

Order matters for uninstall, which walks the registry backwards: items come after
suppliers (they list them as Item Supplier rows) and customers after payment
terms, so the reverse walk removes dependants first.
"""

from demo_data import naming
from demo_data.packs import template_fields
from demo_data.planner import Plan, PlanError, ref, weighted

TERM_DAYS = {"net_15": 15, "net_30": 30, "net_45": 45, "net_60": 60}
SUPPLIER_REGISTERED_SHARE = 0.9


def plan_masters(plan: Plan):
	families = plan_items_per_family(plan)
	plan_payment_terms(plan)
	plan_item_groups(plan)
	suppliers = plan_suppliers(plan)
	plan_items(plan, families, suppliers)
	plan_customers(plan)


# ---------------------------------------------------------------- terms and groups
def used_terms(pack) -> list[str]:
	return sorted({t for c in pack["channels"] for t in c["payment"] if t in TERM_DAYS}, key=TERM_DAYS.get)


def plan_payment_terms(plan: Plan):
	for term in used_terms(plan.ctx.pack):
		days = TERM_DAYS[term]
		plan.add(
			f"M:terms:{term}",
			"Payment Terms Template",
			"payment_terms",
			{"title": f"Net {days}", "days": days},
		)


def plan_item_groups(plan: Plan):
	for group in plan.ctx.pack["catalog"]["item_groups"]:
		plan.add(f"M:item_group:{group}", "Item Group", "item_group", {"name": group})


# ---------------------------------------------------------------- parties
def other_regions(locale, home: str) -> list[str]:
	return [s for s in locale.regions() if s != home]


def pick_region(rng, locale, home: str, home_share: float) -> str:
	return home if rng.random() < home_share else rng.choice(other_regions(locale, home))


def unique_name(rng, make, taken: set[str], what: str) -> str:
	for _ in range(200):
		name = make()
		if name not in taken:
			taken.add(name)
			return name
	raise PlanError(f"ran out of unique {what} names; add words to the pools")


def business_party(
	rng, locale, region: str, nouns: list[str], taken: set[str], registered: bool, category: str
) -> dict:
	name = unique_name(rng, lambda: locale.business_name(rng, nouns), taken, "business")
	first, last = locale.person(rng, region)
	tax = locale.business_tax(rng, name, region, registered, category)  # draws before the address
	return {
		"name": name,
		"type": "Company",
		**tax,
		"address": locale.address(rng, region),
		"contact": {
			"first_name": first,
			"last_name": last,
			"email": naming.email_for_business(name),
			"mobile": locale.phone(rng),
		},
	}


def plan_suppliers(plan: Plan) -> list[str]:
	ctx, pack = plan.ctx, plan.ctx.pack
	locale = ctx.locale
	parties = pack["parties"]
	rng = ctx.rng("suppliers")
	taken: set[str] = set()
	keys = []
	for i in range(ctx.size["suppliers"]):
		region = pick_region(rng, locale, ctx.home_state, parties["supplier_home_state_share"])
		registered = rng.random() < SUPPLIER_REGISTERED_SHARE
		party = business_party(rng, locale, region, parties["supplier_nouns"], taken, registered, "Registered Regular")
		party["group"] = parties["supplier_group"]
		keys.append(plan.add(f"M:supplier:S{i + 1:04d}", "Supplier", "supplier", party))
	return keys


def plan_customers(plan: Plan):
	ctx, pack = plan.ctx, plan.ctx.pack
	locale = ctx.locale
	parties, behavior = pack["parties"], pack["behavior"]
	rng = ctx.rng("customers")
	taken: set[str] = set()
	channels = pack["channels"]
	b2c_share = sum(c["share"] for c in channels if c["party_class"] == "b2c")
	b2b_channels = {c["id"]: c["share"] for c in channels if c["party_class"] == "b2b"}
	b2c_channels = {c["id"]: c["share"] for c in channels if c["party_class"] == "b2c"}
	total = ctx.size["customers"]
	n_b2c = round(total * b2c_share) if b2b_channels else total
	if b2b_channels and total > 1:
		n_b2c = min(max(n_b2c, 1 if b2c_channels else 0), total - 1)

	if parties.get("walk_in_customer") and b2c_channels:
		plan.add(
			"M:customer:walk-in",
			"Customer",
			"customer",
			{
				"name": "Walk-in Customer",
				"type": "Individual",
				"group": parties["customer_group"]["b2c"],
				**locale.individual_tax(),
				"channel": weighted(rng, b2c_channels),
				"address": locale.address(rng, ctx.home_state),
			},
		)
		taken.add("Walk-in Customer")

	for i in range(total):
		key = f"M:customer:C{i + 1:04d}"
		if i < n_b2c:
			name = unique_name(rng, lambda: " ".join(locale.person(rng, ctx.home_state)), taken, "person")
			first, last = name.split(" ", 1)
			params = {
				"name": name,
				"type": "Individual",
				"group": parties["customer_group"]["b2c"],
				**locale.individual_tax(),
				"channel": weighted(rng, b2c_channels),
				"address": locale.address(rng, ctx.home_state),
				"contact": {
					"first_name": first,
					"last_name": last,
					"email": naming.email_for_person(rng, first, last),
					"mobile": locale.phone(rng),
				},
			}
		else:
			home_share = locale.customer_home_share(behavior, ctx.sales_tax)
			region = pick_region(rng, locale, ctx.home_state, home_share)
			registered, category = locale.customer_category(rng, behavior, ctx.sales_tax)
			params = business_party(rng, locale, region, parties["customer_nouns"], taken, registered, category)
			params["group"] = parties["customer_group"]["b2b"]
			channel_id = weighted(rng, b2b_channels)
			params["channel"] = channel_id
			channel = next(c for c in pack["channels"] if c["id"] == channel_id)
			term = weighted(rng, channel["payment"])
			if term in TERM_DAYS:
				params["payment_terms"] = ref(f"M:terms:{term}")
		plan.add(key, "Customer", "customer", params)
	ensure_channel_members(plan)


def ensure_channel_members(plan: Plan):
	"""Every channel needs a customer, or its whole flow (e.g. quotations) is missing.

	With few customers (micro) a weighted draw can leave a channel empty; then the
	busiest channel of the same class gives up its last customer. Larger sizes are
	untouched, so their plans do not change.
	"""
	channels = plan.ctx.pack["channels"]
	customers = [d for d in plan.docs if d.doctype == "Customer" and d.key != "M:customer:walk-in"]
	for channel in channels:
		def members(cid):
			return [d for d in customers if d.params.get("channel") == cid]

		if members(channel["id"]):
			continue
		peers = [c["id"] for c in channels if c["party_class"] == channel["party_class"] and c is not channel]
		donor = max(peers, key=lambda cid: len(members(cid)), default=None)
		if not donor or len(members(donor)) < 2:
			continue
		moved = members(donor)[-1]
		moved.params["channel"] = channel["id"]
		term = max(channel["payment"], key=channel["payment"].get)  # the channel's usual terms
		if term in TERM_DAYS:
			moved.params["payment_terms"] = ref(f"M:terms:{term}")
		else:
			moved.params.pop("payment_terms", None)


# ---------------------------------------------------------------- items
def plan_items_per_family(plan: Plan) -> list[tuple[dict, int]]:
	"""Spread size.items over families in proportion to their pack counts (largest remainder)."""
	families = plan.ctx.pack["catalog"]["families"]
	target = max(plan.ctx.size["items"], len(families))
	weights = [f["count"] for f in families]
	total = sum(weights)
	exact = [target * w / total for w in weights]
	counts = [max(1, int(x)) for x in exact]
	order = sorted(range(len(families)), key=lambda i: exact[i] - int(exact[i]), reverse=True)
	i = 0
	while sum(counts) < target:
		counts[order[i % len(order)]] += 1
		i += 1
	while sum(counts) > target:
		j = max(range(len(counts)), key=lambda k: counts[k])
		counts[j] -= 1
	return list(zip(families, counts, strict=True))


def nice_price(value: float) -> int:
	"""Retail-looking prices: 24,999 rather than 24,713."""
	if value >= 1000:
		return int(round(value / 500) * 500) - 1
	return int(round(value / 10) * 10) - 1


def item_code_prefix(family: dict) -> str:
	return family.get("code_prefix") or family["id"].upper().replace("_", "-")


def plan_items(plan: Plan, families: list[tuple[dict, int]], suppliers: list[str]):
	catalog = plan.ctx.pack["catalog"]
	series = catalog.get("series") or []
	rng = plan.ctx.rng("items")
	price_rng = plan.ctx.rng("prices")
	supplier_rng = plan.ctx.rng("item-suppliers")
	taken: set[str] = set()
	shuffled = suppliers[:]
	supplier_rng.shuffle(shuffled)
	items = []

	for f_index, (family, count) in enumerate(families):
		fields = template_fields(family["name_template"])
		options = family.get("options") or {}
		combos = (len(series) if "series" in fields else 1) * _product(
			len(options[k]) for k in fields if k != "series"
		)
		if combos < count:
			raise PlanError(
				f"family {family['id']} needs {count} names but its template allows only {combos}"
			)
		primary = shuffled[f_index % len(shuffled)] if shuffled else None
		secondary = supplier_rng.choice(shuffled) if shuffled and supplier_rng.random() < 0.3 else None
		family_suppliers = [s for s in dict.fromkeys([primary, secondary]) if s]

		for n in range(count):
			name = unique_name(
				rng,
				lambda family=family, options=options: family["name_template"].format(
					series=rng.choice(series) if series else "",
					**{k: rng.choice(v) for k, v in options.items()},
				),
				taken,
				family["id"],
			)
			low, high = family["price_range"]
			price = nice_price(price_rng.uniform(low, high))
			cost = round(price * price_rng.uniform(*family["cost_ratio"]), -1)
			code = f"{item_code_prefix(family)}-{n + 1:03d}"
			items.append(code)
			plan.add(
				f"M:item:{code}",
				"Item",
				"item",
				{
					"code": code,
					"name": name,
					"group": ref(f"M:item_group:{family['group']}"),
					"family": family["id"],
					**plan.ctx.locale.item_tax(family, plan.ctx.pack),
					"uom": family.get("uom", "Nos"),
					"cost": cost,
					"reorder": family["reorder"],
					"suppliers": [ref(s) for s in family_suppliers],
				},
			)
			plan.add(
				f"M:price:selling:{code}",
				"Item Price",
				"item_price",
				{"item": ref(f"M:item:{code}"), "list": "selling", "rate": price},
			)
			plan.add(
				f"M:price:buying:{code}",
				"Item Price",
				"item_price",
				{"item": ref(f"M:item:{code}"), "list": "buying", "rate": cost},
			)


def _product(values) -> int:
	out = 1
	for v in values:
		out *= v
	return out
