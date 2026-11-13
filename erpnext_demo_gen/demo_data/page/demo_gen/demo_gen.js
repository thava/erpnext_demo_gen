// DemoGen desk page (design 5.19): status, install (small, medium), verify, uninstall,
// progress of the background job, history and help. Server side: erpnext_demo_gen.api.

const DG_API = "erpnext_demo_gen.api.";
const DG_README = "https://github.com/thava/erpnext_demo_gen#readme";
const DG_POLL_MS = 4000; // while a job is queued or running (in case realtime is not connected)
const DG_WAIT_HINT_S = 10; // a queued job that has not started by then: no worker?

frappe.pages["demo-gen"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("DemoGen"),
		single_column: true,
	});
	wrapper.demo_gen = new DemoGenPage(page);
};

frappe.pages["demo-gen"].on_page_show = function (wrapper) {
	if (wrapper.demo_gen) wrapper.demo_gen.refresh();
};

class DemoGenPage {
	constructor(page) {
		this.page = page;
		this.verify_results = {};
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Demo Data Runs"), () => frappe.set_route("List", "Demo Data Run"));
		this.page.add_menu_item(__("README"), () => window.open(DG_README, "_blank"));
		this.$body = $(`<div class="demo-gen">
			<style>
				.demo-gen { padding: var(--padding-md) var(--padding-lg); }
				.demo-gen .dg-card { padding: var(--padding-lg); margin-bottom: var(--margin-lg); }
				.demo-gen .dg-card h4 { margin: 0 0 var(--margin-md); font-size: var(--text-lg); }
				.demo-gen .dg-facts { display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin-bottom: var(--margin-md); }
				.demo-gen .dg-facts dt { color: var(--text-muted); font-weight: normal; }
				.demo-gen .dg-facts dd { margin: 0; }
				.demo-gen .dg-actions .btn { margin: 0 8px 8px 0; }
				.demo-gen .dg-log { max-height: 220px; overflow: auto; font-size: var(--text-sm); background: var(--subtle-fg); padding: 8px; border-radius: var(--border-radius); white-space: pre-wrap; }
				.demo-gen .dg-muted { color: var(--text-muted); }
				.demo-gen .dg-check { padding: 2px 0; }
				.demo-gen .dg-check .dg-ok { color: var(--green-600); }
				.demo-gen .dg-check .dg-fail { color: var(--red-600); }
				.demo-gen .dg-note { background: var(--subtle-accent); padding: 10px 12px; border-radius: var(--border-radius); margin: var(--margin-md) 0; }
				.demo-gen .dg-help code { white-space: pre-wrap; }
				.demo-gen .progress { height: 8px; margin: 8px 0; }
			</style>
			<div class="dg-intro dg-muted" style="margin-bottom: var(--margin-lg)"></div>
			<div class="dg-job"></div>
			<div class="dg-status"></div>
			<div class="dg-install"></div>
			<div class="dg-history"></div>
			<div class="dg-help"></div>
		</div>`).appendTo(this.page.main);
		this.$body
			.find(".dg-intro")
			.text(
				__(
					"DemoGen, an extended demo data generator for ERPNext, adds a demo company with months of realistic transactions (India, United States, UAE, Germany) and removes it again."
				)
			);
		frappe.realtime.on("demo_gen_progress", (live) => this.on_live(live));
		this.render_help();
		// the first refresh comes from on_page_show, which follows on_page_load
	}

	// ------------------------------------------------------------ state
	async refresh() {
		clearTimeout(this.poll);
		let state;
		try {
			state = await frappe.xcall(DG_API + "get_state");
		} catch (e) {
			return; // frappe shows the error
		}
		const was_active = this.state && this.state.job.active;
		this.state = state;
		this.render_job();
		this.render_status();
		this.render_history();
		if (!state.job.active) {
			if (was_active || !this.form) this.render_install();
		} else {
			this.$body.find(".dg-install").empty();
			this.form = null;
			this.poll = setTimeout(() => this.refresh(), DG_POLL_MS);
		}
	}

	on_live(live) {
		if (!this.state) return;
		const before = this.state.job.status;
		Object.assign(this.state.job, live);
		this.render_job();
		if (["done", "failed"].includes(live.status) && before !== live.status) this.refresh();
	}

	// ------------------------------------------------------------ job progress
	render_job() {
		const $job = this.$body.find(".dg-job").empty();
		const job = this.state.job;
		if (!job.action || !job.status) return;
		const action = job.action === "uninstall" ? __("Uninstall") : __("Install");
		const $card = $(`<div class="frappe-card dg-card"><h4></h4><div class="dg-body"></div></div>`).appendTo($job);
		const $b = $card.find(".dg-body");
		const title = {
			queued: __("{0}: queued", [action]),
			running: __("{0}: running", [action]),
			done: __("{0}: finished", [action]),
			failed: __("{0}: failed", [action]),
			stopped: __("{0}: stopped", [action]),
		}[job.status] || action;
		$card.find("h4").text(title);

		if (job.status === "queued") {
			// measured in the browser: server and browser clocks or time zones may differ
			if (this.queued_since?.key !== job.queued_at) this.queued_since = { key: job.queued_at, at: Date.now() };
			const seconds = (Date.now() - this.queued_since.at) / 1000;
			if (seconds <= DG_WAIT_HINT_S) setTimeout(() => this.render_job(), (DG_WAIT_HINT_S + 1) * 1000);
			$b.append(`<p>${__("Waiting for a background worker to pick up the job...")}</p>`);
			if (!this.state.workers || seconds > DG_WAIT_HINT_S) {
				$b.append(
					`<div class="dg-note">${__(
						"Waiting for a background worker (is bench start running?). The job runs on the long queue; {0} worker(s) listen to it now.",
						[this.state.workers]
					)}</div>`
				);
			}
		}
		if (job.status === "running" && job.total) {
			const pct = Math.floor((100 * (job.done || 0)) / job.total);
			const left = job.left != null ? __(", about {0} left", [this.duration(job.left)]) : "";
			$b.append(`<div class="progress"><div class="progress-bar" style="width:${pct}%"></div></div>`);
			$b.append(
				$("<p>").text(__("{0} of {1} {2}{3}", [job.done || 0, job.total, job.verb || "", left]))
			);
		} else if (job.status === "running" && job.message) {
			$b.append($("<p>").text(job.message));
		}
		if (job.status === "failed" && job.error) {
			$b.append($(`<pre class="dg-log" style="color: var(--red-600)"></pre>`).text(job.error));
		}
		if (job.status === "stopped") {
			$b.append(
				`<p>${__(
					"The job is no longer running (a worker restart or timeout). The run can be resumed: what was written is kept."
				)}</p>`
			);
		}
		if (job.status === "done") {
			$b.append($("<p>").text(job.message || __("Done.")));
		}
		if (job.lines && job.lines.length && job.status !== "queued") {
			const $details = $(`<details><summary class="dg-muted">${__("Log")}</summary><pre class="dg-log"></pre></details>`);
			$details.find("pre").text(job.lines.join("\n"));
			if (job.status !== "done") $details.attr("open", true);
			$b.append($details);
			const pre = $details.find("pre")[0];
			pre.scrollTop = pre.scrollHeight;
		}
	}

	// ------------------------------------------------------------ installed runs
	render_status() {
		const $s = this.$body.find(".dg-status").empty();
		const runs = this.state.runs;
		if (!runs.length) return;
		for (const run of runs) {
			const $card = $(`<div class="frappe-card dg-card">
				<h4></h4><dl class="dg-facts"></dl><div class="dg-notes"></div>
				<div class="dg-actions"></div><div class="dg-verify"></div></div>`).appendTo($s);
			$card.find("h4").append(
				$("<span>").text(run.company || __("Demo company")),
				" ",
				$(`<span class="indicator-pill ${this.color(run)}"></span>`).text(this.status_label(run))
			);
			const facts = [
				[__("Run"), run.name],
				[__("Country"), run.country_name || run.country],
				[__("Pack"), run.pack_label],
				[__("Size"), `${run.size}${run.months ? " (" + __("{0} months", [run.months]) + ")" : ""}`],
				[__("Seed"), run.seed],
				[__("Data up to"), run.end_date ? frappe.datetime.str_to_user(run.end_date) : ""],
				[__("Home state"), run.home_state],
				[
					__("Documents"),
					format_number(run.documents, null, 0) + (run.failed ? " " + __("({0} failed or skipped)", [run.failed]) : ""),
				],
				[__("Installed"), run.finished_at && run.status === "Completed" ? frappe.datetime.str_to_user(run.finished_at) : ""],
			];
			facts.splice(
				3,
				0,
				[
					__("Tax registration"),
					run.registration === "unregistered"
						? __("not registered (no {0})", [run.tax_id_name])
						: run.tax_id
						? __("registered, {0} {1} (imaginary)", [run.tax_id_name, run.tax_id])
						: __("registered"),
				]
			);
			const $dl = $card.find(".dg-facts");
			for (const [k, v] of facts) {
				if (v === undefined || v === null || v === "") continue;
				$dl.append($("<dt>").text(k), $("<dd>").text(v));
			}
			if (run.wizard) {
				$card.find(".dg-notes").append(
					`<div class="dg-note">${__(
						"Installed into your own company (CLI --use-wizard-company). Uninstall removes only the demo's documents, one by one, after a backup."
					)}</div>`
				);
			}
			const $a = $card.find(".dg-actions");
			const busy = this.state.job.active;
			const button = (label, cls, fn) =>
				$(`<button class="btn btn-sm ${cls}"></button>`).text(label).prop("disabled", busy).on("click", fn).appendTo($a);
			if (run.status === "Completed") button(__("Verify"), "btn-default", () => this.verify(run, $card));
			if (run.stopped || run.status === "Failed") {
				if (run.status !== "Uninstalling") button(__("Resume install"), "btn-primary", () => this.resume(run));
			}
			button(run.status === "Uninstalling" ? __("Retry uninstall") : __("Uninstall"), "btn-danger", () => this.uninstall(run));
			if (run.company_exists) {
				button(__("Open company"), "btn-default", () => frappe.set_route("Form", "Company", run.company));
			}
			if (run.company_exists && run.company !== this.state.default_company && !run.wizard) {
				$card.find(".dg-notes").append(
					`<div class="dg-muted">${__("The default company is now {0}; change it in Global Defaults.", [
						frappe.utils.escape_html(this.state.default_company || ""),
					])}</div>`
				);
			}
			if (this.verify_results[run.name]) this.show_checks($card.find(".dg-verify"), this.verify_results[run.name]);
		}
	}

	status_label(run) {
		if (run.stopped) return __("{0} (stopped)", [__(run.status)]);
		return __(run.status);
	}

	color(run) {
		if (run.stopped || run.status === "Failed") return "red";
		return { Completed: "green", Running: "orange", Planned: "orange", Uninstalling: "orange" }[run.status] || "gray";
	}

	async verify(run, $card) {
		const $v = $card.find(".dg-verify").html(`<p class="dg-muted">${__("Checking...")}</p>`);
		try {
			const r = await frappe.xcall(DG_API + "verify", { run: run.name });
			this.verify_results[run.name] = r.checks;
			this.show_checks($v, r.checks);
		} catch (e) {
			$v.empty();
		}
	}

	show_checks($v, checks) {
		const failed = checks.filter((c) => !c.ok).length;
		$v.empty().append(
			$("<p>").append(
				$("<strong>").text(
					failed ? __("{0} of {1} checks failed", [failed, checks.length]) : __("All {0} checks passed", [checks.length])
				)
			)
		);
		for (const c of checks) {
			const $row = $(`<div class="dg-check"><span></span> <span class="dg-name"></span> <span class="dg-muted"></span></div>`);
			$row.find("span").eq(0).addClass(c.ok ? "dg-ok" : "dg-fail").text(c.ok ? "✓" : "✗");
			$row.find(".dg-name").text(c.name);
			$row.find(".dg-muted").text(c.detail ? "· " + c.detail : "");
			$v.append($row);
		}
	}

	uninstall(run) {
		const company = run.company || "";
		const d = new frappe.ui.Dialog({
			title: __("Uninstall {0}", [run.name]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${
						run.wizard
							? __("This removes the demo's documents from {0}, one by one; your own documents stay.", [
									`<strong>${frappe.utils.escape_html(company)}</strong>`,
							  ])
							: __(
									"This deletes the demo company {0} with all its documents and restores your previous default company.",
									[`<strong>${frappe.utils.escape_html(company)}</strong>`]
							  )
					}</p>`,
				},
				{ fieldname: "confirm_company", fieldtype: "Data", label: __("Type the company name to confirm"), reqd: 1 },
			],
			primary_action_label: __("Uninstall"),
			primary_action: async (values) => {
				try {
					await frappe.xcall(DG_API + "start_uninstall", { run: run.name, confirm_company: values.confirm_company });
				} catch (e) {
					return; // frappe has shown the reason; the dialog stays open
				}
				d.hide();
				this.refresh();
			},
		});
		d.get_primary_btn().removeClass("btn-primary").addClass("btn-danger");
		d.show();
	}

	async resume(run) {
		try {
			await frappe.xcall(DG_API + "resume_install", { run: run.name });
		} catch (e) {
			return;
		}
		this.refresh();
	}

	// ------------------------------------------------------------ install form
	async render_install() {
		const token = (this.install_token = (this.install_token || 0) + 1);
		const $i = this.$body.find(".dg-install").empty();
		this.form = null;
		if (this.state.runs.length) {
			$i.append(
				`<p class="dg-muted">${__("One demo at a time: uninstall it to install another (the CLI can do more).")}</p>`
			);
			return;
		}
		if (!this.options) this.options = await frappe.xcall(DG_API + "get_install_options");
		if (token !== this.install_token) return; // a newer render started while this one waited
		$i.empty();
		const countries = this.options.countries;
		const $card = $(`<div class="frappe-card dg-card"><h4>${__("Install demo data")}</h4>
			<div class="dg-form"></div><div class="dg-size dg-muted"></div><div class="dg-warning"></div>
			<div class="dg-note"></div><div class="dg-actions"></div></div>`).appendTo($i);
		$card.find(".dg-note").html(
			__(
				"DemoGen creates a new demo company and makes it the default company. You can switch the default back at any time (Global Defaults), and uninstall restores your previous default. Installing into your own company is not offered here (CLI only)."
			)
		);
		const usable = (c) => !c.missing_apps.length && !c.site_problem;
		const first = countries.find((c) => c.is_site_country && usable(c)) || countries.find(usable) || countries[0];
		const form = new frappe.ui.FieldGroup({
			parent: $card.find(".dg-form"),
			fields: [
				{
					fieldname: "country",
					fieldtype: "Select",
					label: __("Country"),
					options: countries.map((c) => ({
						value: c.code,
						label: `${c.name} (${c.currency})${usable(c) ? "" : " - " + __("not on this site")}`,
					})),
					default: first.code,
					reqd: 1,
					change: () => this.on_country(),
				},
				{ fieldname: "pack", fieldtype: "Select", label: __("Pack"), reqd: 1, change: () => this.on_pack() },
				{ fieldname: "size", fieldtype: "Select", label: __("Size"), reqd: 1, change: () => this.on_size() },
				{ fieldname: "registered", fieldtype: "Check", label: __("Registered for tax"), default: 1 },
				{ fieldtype: "Column Break" },
				{ fieldname: "home_state", fieldtype: "Select", label: __("Home state") },
				{
					fieldname: "company_name",
					fieldtype: "Data",
					label: __("Company name"),
					description: __("Leave empty for a generated name"),
				},
				{ fieldtype: "Column Break" },
				{ fieldname: "seed", fieldtype: "Int", label: __("Seed"), default: 1, description: __("Same seed, same data") },
				{
					fieldname: "end_date",
					fieldtype: "Date",
					label: __("Data up to"),
					default: frappe.datetime.get_today(),
				},
			],
		});
		form.make();
		this.form = form;
		this.$install_card = $card;
		$(`<button class="btn btn-primary btn-sm"></button>`)
			.text(__("Install"))
			.on("click", () => this.install())
			.appendTo($card.find(".dg-actions"));
		this.on_country();
	}

	country() {
		return this.options.countries.find((c) => c.code === this.form.get_value("country"));
	}

	pack() {
		const c = this.country();
		return c && c.packs.find((p) => p.name === this.form.get_value("pack"));
	}

	on_country() {
		const c = this.country();
		if (!c) return;
		const pack = this.form.get_field("pack");
		pack.df.options = c.packs.map((p) => ({ value: p.name, label: `${p.name}: ${p.title || ""}` }));
		pack.refresh();
		this.form.set_value("pack", c.default_pack || c.packs[0].name);
		const home = this.form.get_field("home_state");
		home.df.options = c.home_states;
		home.refresh();
		const reg = this.form.get_field("registered");
		reg.df.label = c.registration_label; // translated on the server
		reg.df.read_only = c.unregistered.offered ? 0 : 1;
		reg.df.description = c.unregistered.offered
			? __("Untick for a business not registered for {0}: no {0} on sales, and the {0} paid on purchases becomes part of the cost.", [c.tax])
			: c.unregistered.reason;
		reg.refresh();
		this.form.set_value("registered", 1);
		const $w = this.$install_card.find(".dg-warning").empty();
		if (c.missing_apps.length) {
			$w.append(
				`<div class="dg-note" style="color: var(--red-600)">${__("{0} needs these apps installed on the site first: {1}", [
					c.name,
					c.missing_apps.join(", "),
				])}</div>`
			);
		}
		if (c.site_problem) {
			$w.append($(`<div class="dg-note" style="color: var(--red-600)"></div>`).text(c.site_problem));
		}
		this.$install_card.find(".dg-actions .btn").prop("disabled", !!(c.missing_apps.length || c.site_problem));
		this.on_pack();
	}

	on_pack() {
		const p = this.pack();
		if (!p) return;
		const size = this.form.get_field("size");
		size.df.options = p.sizes.map((s) => ({ value: s.size, label: s.size }));
		size.refresh();
		if (!p.sizes.find((s) => s.size === this.form.get_value("size"))) this.form.set_value("size", p.sizes[0].size);
		this.form.set_value("home_state", p.home_state);
		this.on_size();
	}

	on_size() {
		const p = this.pack();
		const s = p && p.sizes.find((x) => x.size === this.form.get_value("size"));
		this.$install_card
			.find(".dg-size")
			.text(
				s
					? __("{0}: {1} months of data, about {2} documents, about {3} to install. Large is CLI only.", [
							s.size,
							s.months,
							s.documents.toLocaleString(),
							s.time,
					  ])
					: ""
			);
	}

	async install(force = 0) {
		const values = this.form.get_values();
		if (!values) return;
		values.unregistered = values.registered ? 0 : 1;
		delete values.registered;
		let r;
		try {
			r = await frappe.xcall(DG_API + "start_install", { ...values, force });
		} catch (e) {
			return; // frappe has shown the refusal
		}
		if (r.confirm) {
			frappe.confirm(
				`<pre class="dg-log" style="white-space: pre-wrap">${frappe.utils.escape_html(r.confirm)}</pre><p>${frappe.utils.escape_html(
					r.question || __("Install anyway?")
				)}</p>`,
				() => this.install(1)
			);
			return;
		}
		frappe.show_alert({ message: __("Install queued"), indicator: "blue" });
		this.refresh();
	}

	// ------------------------------------------------------------ history and help
	render_history() {
		const $h = this.$body.find(".dg-history").empty();
		const rows = this.state.history;
		if (!rows.length) return;
		const $card = $(`<div class="frappe-card dg-card"><h4>${__("Recent runs")}</h4>
			<div class="table-responsive"><table class="table table-sm"><thead><tr></tr></thead><tbody></tbody></table></div>
			<a class="dg-all"></a></div>`).appendTo($h);
		for (const k of [__("Run"), __("Status"), __("Pack"), __("Size"), __("Company"), __("Started"), __("Finished")]) {
			$card.find("thead tr").append($("<th>").text(k));
		}
		for (const r of rows) {
			const $tr = $("<tr>").appendTo($card.find("tbody"));
			$tr.append(
				$("<td>").append($("<a>").text(r.name).attr("href", `/desk/demo-data-run/${encodeURIComponent(r.name)}`)),
				$("<td>").text(__(r.status)),
				$("<td>").text(r.pack_label),
				$("<td>").text(r.size),
				$("<td>").text(r.company || ""),
				$("<td>").text(r.started_at ? frappe.datetime.str_to_user(r.started_at) : ""),
				$("<td>").text(r.finished_at ? frappe.datetime.str_to_user(r.finished_at) : "")
			);
		}
		$card
			.find(".dg-all")
			.text(__("All runs and their events"))
			.attr("href", "#")
			.on("click", (e) => {
				e.preventDefault();
				frappe.set_route("List", "Demo Data Run");
			});
	}

	render_help() {
		const code = (s) => `<code>${frappe.utils.escape_html(s)}</code>`;
		const $help = $(`<div class="frappe-card dg-card dg-help"><details><summary><h4 style="display:inline">${__(
			"Help and command line"
		)}</h4></summary><div class="dg-help-body" style="margin-top: var(--margin-md)"></div></details></div>`);
		$help.find(".dg-help-body").html(`
			<p>${__(
				"DemoGen is separate from ERPNext's built-in demo data: it never uses ERPNext's 'Delete Demo Data' item. Remove DemoGen data here or with the command line."
			)}</p>
			<p><strong>${__("Sizes")}</strong>: ${__(
				"small: 3 months, about 300 documents, about 1 minute; medium: 12 months, about 1,200 documents, about 5 minutes; large: 24 months, about 19,000 documents, 1 to 2 hours (command line only)."
			)}</p>
			<p><strong>${__("The same from the command line")}</strong></p>
			<p>${code("bench --site SITE demo-gen install --country IN --size medium")}<br>
			${code("bench --site SITE demo-gen status")}<br>
			${code("bench --site SITE demo-gen verify")}<br>
			${code("bench --site SITE demo-gen uninstall")}<br>
			${code("bench --site SITE demo-gen history")}</p>
			<p><strong>${__("Command line only")}</strong>: ${code("--size large")}, ${code("--use-wizard-company")} ${__(
				"(into your own company)"
			)}, ${code(
				"uninstall --registry-only"
			)}, ${code("uninstall --no-backup")}.</p>
			<p><strong>${__("Snapshots")}</strong>: ${__(
				"ready-made demo sites to restore in seconds, in the monthly snapshots-YYYY-MM releases on GitHub, or built with"
			)} ${code("bench demo-gen snapshot build --country IN --size medium")}.</p>
			<p><a href="${DG_README}" target="_blank" rel="noopener">${__("README: the full guide")}</a></p>
		`);
		this.$body.find(".dg-help").replaceWith($help);
	}

	duration(seconds) {
		seconds = Math.max(0, Math.round(seconds));
		if (seconds < 90) return __("{0} s", [seconds]);
		return __("{0} min", [Math.round(seconds / 60)]);
	}
}
