"""End-to-end smoke test: install, verify, uninstall, and prove nothing else changed.

Not a unit test (it commits and takes minutes), so it is not named test_*.py.
Run it on a disposable site that already has some non-demo data, e.g.:

    bench --site demo-data.localhost execute erpnext_demo_gen.tests.smoke.run \
        --kwargs '{"country": "IN", "pack": "furniture_store", "seed": 11}'

It snapshots row counts of the tables a demo touches, installs, runs verify,
uninstalls, and fails if any count differs from the snapshot (M-9 gate) or if
the default company was not restored.
"""

import frappe

# Tables whose row counts must be identical before install and after uninstall.
WATCHED = (
	"Company",
	"Account",
	"Cost Center",
	"Warehouse",
	"Fiscal Year",
	"Customer",
	"Supplier",
	"Item",
	"Item Group",
	"Item Price",
	"Address",
	"Contact",
	"Dynamic Link",
	"Payment Terms Template",
	"Sales Taxes and Charges Template",
	"Sales Taxes and Charges",
	"Purchase Taxes and Charges Template",
	"Bank",
	"Bank Account",
	"Mode of Payment",
	"Mode of Payment Account",
	"Purchase Taxes and Charges",
	"Item Tax Template",
	"Item Tax Template Detail",
	"Mode of Payment Account",
	"Item Default",
	"Property Setter",
	"GL Entry",
	"Stock Ledger Entry",
	"Payment Ledger Entry",
	"Bin",
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
	"Repost Item Valuation",
)


def snapshot() -> dict:
	counts = {dt: frappe.db.count(dt) for dt in WATCHED}
	counts["default company"] = frappe.db.get_single_value("Global Defaults", "default_company")
	counts["demo company"] = frappe.db.get_single_value("Global Defaults", "demo_company")
	if frappe.db.exists("DocType", "GST Settings"):  # India (india_compliance)
		counts["SEZ/overseas enabled"] = frappe.db.get_single_value("GST Settings", "enable_overseas_transactions")
	return counts


def run(
	country: str | None = None,
	pack: str | None = None,
	size: str = "small",
	seed: int = 11,
	end_date: str | None = None,
	use_wizard_company: bool = False,
	registry_only: bool = False,
	no_gst: bool = False,
	fictitious_gstin: bool = False,
):
	from erpnext_demo_gen import service

	before = snapshot()
	if not country:
		raise ValueError('pass the country explicitly, e.g. "country": "IN"')
	run_doc = service.install(
		pack,
		size,
		int(seed),
		end_date,
		use_wizard_company=use_wizard_company,
		force=True,
		no_gst=no_gst,
		fictitious_gstin=fictitious_gstin,
		country=country,
	)
	_, checks = service.verify(run_doc.name)
	failed = [c for c in checks if not c.ok]
	for c in checks:
		print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail}")

	service.uninstall(run_doc.name, registry_only=registry_only, no_backup=True)
	after = snapshot()
	changed = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
	if changed:
		print("Changed by install + uninstall:", changed)
	else:
		print(f"All {len(before)} watched counts are back to their starting values")

	if failed or changed:
		raise AssertionError(
			f"smoke test failed: {len(failed)} verify checks failed, {len(changed)} counts changed"
		)
	print("smoke test passed")
