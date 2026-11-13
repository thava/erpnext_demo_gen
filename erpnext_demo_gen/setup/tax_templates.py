"""Tax templates: the orphaned-row workaround (F-26) and no-ITC purchase templates (F-38).

Orphaned rows (F-26).

Company.on_trash deletes a company's Sales/Purchase Taxes and Charges Templates
and Item Tax Templates with raw SQL, leaving their child rows behind. When a
company with the same abbreviation is created later, india_compliance creates
templates with the same names and the orphans reattach, so every tax row
appears twice (or more) and GST is charged twice.
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


NOT_RECOVERABLE_ACCOUNT = "GST Not Recoverable"
NO_ITC_TITLE = "Input GST (not recoverable)"
ITEM_TAX_TITLE = "GST {rate:g}% (not recoverable)"


def no_itc_template(abbr: str) -> str:
	"""Name of the purchase template an unregistered company uses for registered suppliers."""
	return f"{NO_ITC_TITLE} - {abbr}"


def not_recoverable_account(abbr: str) -> str:
	return f"{NOT_RECOVERABLE_ACCOUNT} - {abbr}"


def ensure_no_itc_templates(run, company: str, abbr: str) -> dict[float, str]:
	"""Accounts and templates for a company not registered for GST (--unregistered, F-38, F-51).

	A registered supplier still charges GST, but an unregistered buyer cannot claim it
	back. Neither ERPNext nor india_compliance handles this; the user sets it up:

	    account   "GST Not Recoverable" (expense), not india_compliance's Input Tax accounts
	    purchase  one template, one row on that account, "Valuation and Total":
	              stock items      -> the GST goes into their cost (stock value, then COGS)
	              non-stock items  -> ERPNext makes the row "Total" (nothing to value), so
	                                  the GST is an expense when bought
	    items     Item Tax Templates "GST 5% (not recoverable)" etc. give that account the
	              item's full GST rate (the CGST/SGST/IGST split is not kept)

	The templates carry no tax category, so india_compliance never picks them should the
	company register. Everything is recorded, so uninstall removes it. Returns the item
	tax templates by GST rate.
	"""
	from erpnext_demo_gen.locales.india import GST_RATES

	account = not_recoverable_account(abbr)

	def create_account():
		parent = frappe.db.get_value(
			"Account", {"company": company, "account_name": "Indirect Expenses", "is_group": 1}
		) or frappe.db.get_value(
			"Account", {"company": company, "root_type": "Expense", "is_group": 1}, order_by="lft asc"
		)
		return frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": NOT_RECOVERABLE_ACCOUNT,
				"company": company,
				"parent_account": parent,
				"account_type": "Expense Account",
				"root_type": "Expense",
			}
		).insert(ignore_permissions=True)

	account = run.ensure("setup:gst-not-recoverable-account", create_account)

	def create_purchase_template():
		return frappe.get_doc(
			{
				"doctype": "Purchase Taxes and Charges Template",
				"title": NO_ITC_TITLE,
				"company": company,
				"taxes": [
					{
						"category": "Valuation and Total",
						"add_deduct_tax": "Add",
						"charge_type": "On Net Total",
						"account_head": account,
						"description": "GST paid, not recoverable (no ITC)",
						"rate": 18,  # each item's rate comes from its Item Tax Template
					}
				],
			}
		).insert(ignore_permissions=True)

	run.ensure("setup:no-itc-template", create_purchase_template)

	templates = {}
	for rate in GST_RATES:
		def create_item_template(rate=rate):
			return frappe.get_doc(
				{
					"doctype": "Item Tax Template",
					"title": ITEM_TAX_TITLE.format(rate=rate),
					"company": company,
					"gst_treatment": "Taxable",
					"gst_rate": rate,
					"taxes": [{"tax_type": account, "tax_rate": rate}],
				}
			).insert(ignore_permissions=True)

		templates[float(rate)] = run.ensure(f"setup:no-itc-item-tax:{rate:g}", create_item_template)
	return templates
