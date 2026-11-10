import datetime as dt
from collections import Counter

from frappe.tests import UnitTestCase

from erpnext_demo_gen.packs import load_pack
from erpnext_demo_gen.planner import PlanContext, make_plan


def plan(size="small", seed=1, home="Tamil Nadu", pack_id="furniture_store", sales_tax=True):
	pack = load_pack(pack_id)
	ctx = PlanContext(pack, size, seed, home, dt.date(2025, 11, 9), dt.date(2026, 11, 8), sales_tax)
	return pack, make_plan(ctx)


def by_doctype(docs):
	"""Counts per doctype, leaving out own-use supplies (planner/supplies.py)."""
	return Counter(d.doctype for d in docs if not d.key.startswith("M:supply:") and d.params.get("family") != "supplies")


class TestMasterPlan(UnitTestCase):
	def test_deterministic(self):
		_, a = plan(seed=7)
		_, b = plan(seed=7)
		self.assertEqual([(d.key, d.params) for d in a], [(d.key, d.params) for d in b])
		_, c = plan(seed=8)
		self.assertNotEqual([d.params for d in a], [d.params for d in c])

	def test_small_counts_follow_the_size(self):
		pack, docs = plan()
		size = pack["sizes"]["small"]
		counts = by_doctype(docs)
		self.assertEqual(counts["Item"], size["items"])
		self.assertEqual(counts["Item Price"], 2 * size["items"])
		self.assertEqual(counts["Supplier"], size["suppliers"])
		self.assertEqual(counts["Customer"], size["customers"] + 1)  # + Walk-in Customer
		self.assertEqual(counts["Item Group"], len(pack["catalog"]["item_groups"]) + 1)  # + Office Supplies
		self.assertEqual(counts["Payment Terms Template"], 2)  # net_15, net_30

	def test_medium_scales(self):
		pack, docs = plan("medium")
		self.assertEqual(by_doctype(docs)["Item"], pack["sizes"]["medium"]["items"])

	def test_refs_point_backwards_and_seq_is_ordered(self):
		_, docs = plan()
		seen = set()
		for i, d in enumerate(docs, 1):
			self.assertEqual(d.seq, i)
			self.assertTrue(set(d.depends_on) <= seen, d.key)
			seen.add(d.key)

	def test_names_unique_and_counter_free(self):
		_, docs = plan("medium")
		for doctype in ("Item", "Customer", "Supplier"):
			names = [d.params["name"] for d in docs if d.doctype == doctype]
			self.assertEqual(len(names), len(set(names)), doctype)
		for d in docs:
			if d.doctype == "Item":
				self.assertNotRegex(d.params["name"], r"\b0\d\d\b")  # codes stay out of display names

	def test_parties_have_consistent_gst_data(self):
		from india_compliance.gst_india.utils import validate_gstin

		from erpnext_demo_gen.india.geo import state_code

		_, docs = plan("medium")
		categories = Counter()
		for d in docs:
			if d.doctype not in ("Customer", "Supplier"):
				continue
			p = d.params
			categories[p["gst_category"]] += 1
			if p.get("gstin"):
				validate_gstin(p["gstin"])
				self.assertEqual(p["gstin"][:2], state_code(p["address"]["state"]), d.key)
				self.assertNotEqual(p["gst_category"], "Unregistered")
			else:
				self.assertEqual(p["gst_category"], "Unregistered")
		self.assertGreater(categories["Registered Regular"], 0)
		self.assertGreater(categories["Unregistered"], 0)

	def test_b2c_customers_are_individuals_in_home_state(self):
		_, docs = plan(home="Karnataka")
		b2c = [d.params for d in docs if d.doctype == "Customer" and d.params["type"] == "Individual"]
		self.assertTrue(b2c)
		self.assertTrue(all(p["address"]["state"] == "Karnataka" for p in b2c))

	def test_unregistered_company_sells_only_in_home_state(self):
		# inter-state and SEZ supplies need GST registration (--no-gst)
		_, docs = plan(pack_id="electrical_distributor", home="Karnataka", sales_tax=False)
		customers = [d.params for d in docs if d.doctype == "Customer"]
		self.assertTrue(all(p["address"]["state"] == "Karnataka" for p in customers if p.get("address")))
		self.assertFalse(any(p.get("gst_category") == "SEZ" for p in customers))
		suppliers = [d.params for d in docs if d.doctype == "Supplier"]
		self.assertTrue(any(p["address"]["state"] != "Karnataka" for p in suppliers))

	def test_items_have_prices_with_margin(self):
		_, docs = plan()
		prices = {
			(d.params["list"], d.params["item"]["$ref"]): d.params["rate"]
			for d in docs
			if d.doctype == "Item Price"
		}
		for d in docs:
			if d.doctype == "Item" and d.params["family"] != "supplies":  # supplies are only bought
				key = d.key
				self.assertLess(prices[("buying", key)], prices[("selling", key)])
				self.assertTrue(d.params["suppliers"])


class TestTransactionPlan(UnitTestCase):
	def setUp(self):
		self.pack, self.docs = plan()
		self.tx = [d for d in self.docs if d.key.startswith("T:")]

	def test_transactions_in_date_and_time_order(self):
		stamps = [(d.posting_date, d.posting_time) for d in self.tx]
		self.assertEqual(stamps, sorted(stamps))
		self.assertEqual(len(stamps), len(set(stamps)), "posting times must be unique within a day")
		self.assertTrue(all(dt.date(2025, 11, 9) <= d.posting_date <= dt.date(2026, 11, 8) for d in self.tx))

	def test_funding_comes_first(self):
		self.assertEqual(self.tx[0].builder, "funding_entry")
		self.assertGreater(self.tx[0].params["share_capital"] + self.tx[0].params["term_loan"], 0)

	def test_every_item_is_stocked_on_day_one(self):
		first_day = self.tx[0].posting_date
		opening = {
			line["item"]["$ref"]
			for d in self.tx
			if d.builder == "purchase_order" and d.posting_date == first_day
			for line in d.params["lines"]
		}
		self.assertEqual(opening, {d.key for d in self.docs if d.doctype == "Item"})

	def test_no_item_repeats_within_a_document(self):
		for d in self.tx:
			lines = d.params.get("lines") or []
			items = [line["item"]["$ref"] for line in lines]
			self.assertEqual(len(items), len(set(items)), d.key)

	def test_state_coverage(self):
		builders = Counter(d.builder for d in self.tx)
		for builder in (
			"quotation",
			"sales_order",
			"delivery_note",
			"invoice_from_delivery",
			"counter_sales_invoice",
			"receive_payment",
			"material_request",
			"purchase_order",
			"purchase_receipt",
			"purchase_invoice",
			"pay_supplier",
			"sales_return",
			"cancel",
		):
			self.assertGreater(builders[builder], 0, builder)
		self.assertTrue(any(d.params.get("draft") for d in self.tx if d.builder == "counter_sales_invoice"))
		self.assertTrue(any(d.params.get("fraction") for d in self.tx if d.builder == "receive_payment"))

	def test_sales_volume_follows_size(self):
		invoices = sum(1 for d in self.tx if d.builder in ("counter_sales_invoice", "invoice_from_delivery"))
		target = self.pack["sizes"]["small"]["sales_invoices"]
		self.assertLess(abs(invoices - target), target * 0.15)


def plan_for_pack(pack_id, size="small", seed=1):
	pack = load_pack(pack_id)
	ctx = PlanContext(pack, size, seed, "Tamil Nadu", dt.date(2025, 11, 9), dt.date(2026, 11, 8))
	return pack, make_plan(ctx)


class TestElectricalPack(UnitTestCase):
	def setUp(self):
		self.pack, self.docs = plan_for_pack("electrical_distributor")

	def test_dealer_orders_skip_quotations(self):
		orders = [d for d in self.docs if d.builder == "sales_order"]
		direct = [d for d in orders if "quotation" not in d.params]
		quoted = [d for d in orders if "quotation" in d.params]
		self.assertTrue(direct, "dealer channel orders directly")
		self.assertTrue(quoted, "project channel quotes first")

	def test_channel_quantities(self):
		low, high = next(c for c in self.pack["channels"] if c["id"] == "dealers")["quantity"]
		direct = [d for d in self.docs if d.builder == "sales_order" and "quotation" not in d.params]
		qtys = [line["qty"] for d in direct for line in d.params["lines"]]
		self.assertTrue(all(1 <= q <= high for q in qtys))
		self.assertGreaterEqual(max(qtys), low)


class TestReorderFit(UnitTestCase):
	def test_reorder_levels_cover_medium_demand(self):
		pack, docs = plan_for_pack("furniture_store", "medium")
		pack_levels = {f["id"]: f["reorder"] for f in pack["catalog"]["families"]}
		items = [d for d in docs if d.doctype == "Item" and d.params["family"] != "supplies"]
		raised = sum(1 for d in items if d.params["reorder"]["max"] > pack_levels[d.params["family"]]["max"])
		self.assertGreater(raised, 0)
		for d in items:
			self.assertLess(d.params["reorder"]["min"], d.params["reorder"]["max"])
		invoices = sum(1 for d in docs if d.builder == "purchase_invoice")
		self.assertLess(invoices, 2 * pack["sizes"]["medium"]["purchase_invoices"])


class TestPaymentMethods(UnitTestCase):
	def test_modes_references_and_clearance(self):
		from erpnext_demo_gen.planner.transactions import reconciled_until

		pack, docs = plan()
		banking = pack["banking"]
		payments = [d.params for d in docs if d.builder in ("receive_payment", "pay_supplier", "refund")]
		from erpnext_demo_gen.planner.transactions import planned_mode_names

		modes = Counter(p["mode"] for p in payments)
		self.assertEqual(set(modes), planned_mode_names(banking))
		self.assertEqual(
			planned_mode_names(banking),
			{"Cash", "UPI - ICICI", "Card - ICICI", "UPI - HDFC", "Wire Transfer", "Cheque"},
		)
		# counter UPI and card go to the collection account, everything else to the main one
		for p in payments:
			expected = "cash" if p["mode"] == "Cash" else "collection" if p["mode"].endswith("ICICI") else "main"
			self.assertEqual(p["account"], expected, p)
		transfers = [d.params for d in docs if d.builder == "bank_transfer"]
		self.assertEqual({t["source"] for t in transfers}, {"collection", "cash"})
		sweep_days = {d.posting_date.weekday() for d in docs if d.builder == "bank_transfer"}
		self.assertEqual(sweep_days, {banking["sweep_weekday"]})
		reconciled = reconciled_until(dt.date(2026, 11, 8))
		for p in payments:
			if p["mode"] == "Cash":
				self.assertNotIn("reference", p)
				continue
			self.assertTrue(p["reference"])
			if p["clearance_date"]:
				self.assertLessEqual(p["clearance_date"], reconciled)
		self.assertTrue(any(p.get("clearance_date") for p in payments))
		self.assertTrue(any(p["mode"] != "Cash" and not p["clearance_date"] for p in payments))

	def test_upi_only_for_small_amounts(self):
		from erpnext_demo_gen.planner.transactions import payment_method

		pack, _ = plan()
		ctx = PlanContext(pack, "small", 3, "Tamil Nadu", dt.date(2025, 11, 9), dt.date(2026, 11, 8))
		big = [payment_method(ctx, "customer", 500000, dt.date(2026, 5, 4))["mode"] for _ in range(200)]
		self.assertNotIn("UPI", big)
		self.assertTrue(all(m in ("Wire Transfer", "Cheque") for m in big))
		counter = {payment_method(ctx, "counter", 5000, dt.date(2026, 5, 4))["mode"] for _ in range(200)}
		self.assertEqual(counter, {"Cash", "UPI - ICICI", "Card - ICICI"})


class TestMicro(UnitTestCase):
	def test_every_seed_covers_the_features(self):
		from erpnext_demo_gen.planner.transactions import planned_mode_names

		for pack_id in ("furniture_store", "electrical_distributor"):
			pack = load_pack(pack_id)
			for seed in range(1, 9):
				ctx = PlanContext(pack, "micro", seed, "Tamil Nadu", dt.date(2026, 8, 9), dt.date(2026, 11, 8))
				docs = make_plan(ctx)
				where = f"{pack_id} seed {seed}"
				self.assertLess(len(docs), 420, where)  # about 60 of them own-use supplies
				builders = Counter(d.builder for d in docs)
				for builder in ("quotation", "sales_order", "delivery_note", "invoice_from_delivery", "counter_sales_invoice",
					"sales_return", "cancel", "purchase_order", "purchase_invoice", "pay_supplier", "bank_transfer",
					"stock_issue", "purchase_invoice_from_order"):
					self.assertGreater(builders[builder], 0, f"{where}: {builder}")
				self.assertTrue(any(d.params.get("draft") for d in docs if d.builder == "counter_sales_invoice"), where)
				modes = {d.params["mode"] for d in docs if d.builder in ("receive_payment", "pay_supplier")}
				self.assertEqual(modes, planned_mode_names(pack["banking"]), where)
				upi = [d for d in docs if d.params.get("mode", "").startswith("UPI")]
				self.assertTrue(all("fraction" not in d.params or not d.params["fraction"] or d.params["fraction"] < 1 for d in upi))
