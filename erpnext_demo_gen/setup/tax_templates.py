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


NO_ITC_TITLE = "Input GST {place}-state (no ITC)"


def no_itc_template(place: str, abbr: str) -> str:
	"""Name of the purchase template an unregistered company uses: place is "In" or "Out"."""
	return f"{NO_ITC_TITLE.format(place=place)} - {abbr}"


def ensure_no_itc_templates(run, company: str, abbr: str):
	"""Purchase templates for a company not registered for GST (--unregistered, F-38).

	A registered supplier still charges GST, but an unregistered buyer cannot claim
	it back, so it belongs in the cost of the goods. Neither ERPNext nor
	india_compliance does this for an unregistered company: the user creates
	templates whose rows are "Valuation and Total" and selects them on purchases.
	These copy india_compliance's input templates (same accounts, so per-item GST
	rates from Item Tax Templates still apply) with that one change. They carry no
	tax category, so india_compliance never picks them should the company register.
	"""
	for place in ("In", "Out"):
		source = f"Input GST {place}-state - {abbr}"
		if not frappe.db.exists("Purchase Taxes and Charges Template", source):
			frappe.throw(f"Purchase template {source!r} not found; india_compliance creates it with the company")

		def create(place=place, source=source):
			rows = frappe.get_doc("Purchase Taxes and Charges Template", source).taxes
			return frappe.get_doc(
				{
					"doctype": "Purchase Taxes and Charges Template",
					"title": NO_ITC_TITLE.format(place=place),
					"company": company,
					"taxes": [
						{
							"category": "Valuation and Total",
							"add_deduct_tax": "Add",
							"charge_type": row.charge_type,
							"account_head": row.account_head,
							"description": f"{row.description} (no ITC: part of cost)",
							"rate": row.rate,
						}
						for row in rows
					],
				}
			).insert(ignore_permissions=True)

		run.ensure(f"setup:no-itc-template:{place}", create)
