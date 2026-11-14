"""Tax templates: the orphaned-row workaround and the not-recoverable tax set-up.

Orphaned rows: Company.on_trash deletes a company's tax templates (Sales/Purchase Taxes
and Charges Templates, Item Tax Templates) with raw SQL, leaving their child rows:

    company deleted         -> its template rows stay behind
    new company, same abbr  -> india_compliance creates templates with the same names
                            -> the old rows reattach: every tax row twice, GST charged twice

So: delete_template_rows before deleting a company, purge_orphans before creating one.
"""

import frappe

TEMPLATE_TABLES = (
	("Sales Taxes and Charges Template", "Sales Taxes and Charges"),
	("Purchase Taxes and Charges Template", "Purchase Taxes and Charges"),
	("Item Tax Template", "Item Tax Template Detail"),
)


def delete_template_rows(company: str):
	"""Before deleting a company: remove the child rows its on_trash would orphan."""
	for parent_doctype, child_doctype in TEMPLATE_TABLES:
		names = frappe.get_all(parent_doctype, filters={"company": company}, pluck="name")
		if names:
			frappe.db.delete(child_doctype, {"parenttype": parent_doctype, "parent": ["in", names]})


def purge_orphans(abbr: str) -> int:
	"""Before creating a company: drop orphaned rows that templates named '... - <abbr>' would adopt."""
	removed = 0
	for parent_doctype, child_doctype in TEMPLATE_TABLES:
		parents = frappe.db.sql_list(
			f"""select distinct c.parent from `tab{child_doctype}` c
			left join `tab{parent_doctype}` t on t.name = c.parent
			where c.parenttype = %s and c.parent like %s and t.name is null""",
			(parent_doctype, f"% - {abbr}"),
		)
		for parent in parents:
			removed += frappe.db.count(child_doctype, {"parenttype": parent_doctype, "parent": parent})
			frappe.db.delete(child_doctype, {"parenttype": parent_doctype, "parent": parent})
	return removed


def gst_fields(doc, rate: float = 0):
	"""Fill india_compliance's GST fields on an Item Tax Template, whatever the country.

	india_compliance validates every Item Tax Template on the site, not only Indian ones:

	    Indian company      "Taxable" at its GST rate
	    any other company   "Non-GST", which needs no rate
	"""
	if not doc.meta.has_field("gst_treatment"):
		return
	if frappe.get_cached_value("Company", doc.company, "country") == "India":
		doc.update({"gst_treatment": "Taxable", "gst_rate": rate})
	else:
		doc.update({"gst_treatment": "Non-GST", "gst_rate": 0})


def ensure_not_recoverable(
	run,
	company: str,
	*,
	account_name: str,
	parents: tuple[str, ...],
	purchase_title: str,
	description: str,
	default_rate: float,
	item_templates: dict | None = None,
	tax_category: str | None = None,
	no_tax_title: str | None = None,
) -> dict:
	"""Accounts and templates for a business not registered for tax (--unregistered).

	A registered supplier still charges the tax, but the buyer cannot recover it. Neither
	ERPNext nor the country apps model this; a real user sets it up by hand:

	    account   a "not recoverable" expense account, never the recoverable input-tax ones
	    purchase  one template, one row on that account, "Valuation and Total":
	              stock items      -> the tax goes into their cost (stock value, then COGS)
	              non-stock items  -> ERPNext makes the row "Total" (nothing to value), so
	                                  the tax is an expense when bought
	    items     optional Item Tax Templates {key: (title, rate)} that give the account each
	              item's own rate (India's GST slabs, Germany's 19 % / 7 %); with
	              tax_category, only purchases (which carry that category) pick them, so
	              sales lines never get a rate
	    no tax    optional empty sales and purchase templates: picking one stops ERPNext
	              from applying the company's default (VAT) template

	The templates carry no tax category of their own, so tax rules never pick them should
	the company register. Everything goes through the registry, so uninstall removes it.

	Returns the names: account, purchase, items {key: name}, no_tax_sales, no_tax_purchase,
	tax_category.
	"""

	def create_account():
		parent = None
		for name in parents:
			parent = frappe.db.get_value("Account", {"company": company, "account_name": name, "is_group": 1})
			if parent:
				break
		parent = parent or frappe.db.get_value(
			"Account", {"company": company, "root_type": "Expense", "is_group": 1}, order_by="lft asc"
		)
		return frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"company": company,
				"parent_account": parent,
				"account_type": "Expense Account",
				"root_type": "Expense",
			}
		).insert(ignore_permissions=True)

	out = {"account": run.ensure("setup:not-recoverable:account", create_account)}

	def create_purchase_template():
		return frappe.get_doc(
			{
				"doctype": "Purchase Taxes and Charges Template",
				"title": purchase_title,
				"company": company,
				"taxes": [
					{
						"category": "Valuation and Total",
						"add_deduct_tax": "Add",
						"charge_type": "On Net Total",
						"account_head": out["account"],
						"description": description,
						"rate": default_rate,  # an item's own rate comes from its Item Tax Template
					}
				],
			}
		).insert(ignore_permissions=True)

	out["purchase"] = run.ensure("setup:not-recoverable:purchase-template", create_purchase_template)

	if tax_category:
		out["tax_category"] = run.ensure(
			"setup:not-recoverable:tax-category",
			lambda: frappe.get_doc({"doctype": "Tax Category", "title": tax_category}).insert(ignore_permissions=True),
		)

	out["items"] = {}
	for key, (title, rate) in (item_templates or {}).items():

		def create_item_template(title=title, rate=rate):
			doc = frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"title": title,
					"company": company,
					"taxes": [{"tax_type": out["account"], "tax_rate": rate}],
				}
			)
			gst_fields(doc, rate)
			return doc.insert(ignore_permissions=True)

		out["items"][key] = run.ensure(f"setup:not-recoverable:item-tax:{key}", create_item_template)

	if no_tax_title:
		for doctype, key in (("Sales Taxes and Charges Template", "no_tax_sales"), ("Purchase Taxes and Charges Template", "no_tax_purchase")):
			out[key] = run.ensure(
				f"setup:not-recoverable:{key}",
				lambda doctype=doctype: frappe.get_doc({"doctype": doctype, "title": no_tax_title, "company": company}).insert(
					ignore_permissions=True
				),
			)
	run.update_params(not_recoverable=out)
	return out


def ensure_no_itc_templates(run, company: str) -> dict:
	"""India's not-recoverable set-up (--unregistered).

	    account     "GST Not Recoverable"
	    template    "Input GST (not recoverable)"
	    items       "GST 5% (not recoverable)" etc., at the item's full GST rate

	The CGST/SGST/IGST split is not kept: one template covers in-state and out-of-state.
	"""
	from erpnext_demo_gen.locales.india import GST_RATES

	return ensure_not_recoverable(
		run,
		company,
		account_name="GST Not Recoverable",
		parents=("Indirect Expenses",),
		purchase_title="Input GST (not recoverable)",
		description="GST paid, not recoverable (no ITC)",
		default_rate=18,
		item_templates={f"{rate:g}": (f"GST {rate:g}% (not recoverable)", rate) for rate in GST_RATES},
	)
