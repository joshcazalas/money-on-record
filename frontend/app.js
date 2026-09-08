import { DATASETS, TYPE_LABELS, dateKey, filterRows, csvForRows, officialRecordUrl, filingUrl } from "./data.js";

const app = document.querySelector("#app");
const dialog = document.querySelector("#record-dialog");
const PAGE_SIZE = 20;
const cache = new Map();
const number = new Intl.NumberFormat("en-US");
const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const dateFormat = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const searchIcon = '<svg viewBox="0 0 20 20" fill="none" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5" stroke-width="1.5"/><path d="m13 13 4 4" stroke-width="1.5"/></svg>';
const downloadIcon = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2v10m-4-4 4 4 4-4M3 13v4h14v-4"/></svg>';
let page = "contributions";
let filters = {};
let data;
let visibleRows = [];
let renderVersion = 0;
let searchTimer;

const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const prettyDate = value => {
  const date = new Date(`${dateKey(value)}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? "Not reported" : dateFormat.format(date);
};
const external = (url, label, attributes = "") => `<a href="${escape(url)}" target="_blank" rel="noreferrer" ${attributes}>${label} <span aria-hidden="true">↗</span><span class="visually-hidden"> (external source, new tab)</span></a>`;
const unique = (rows, field) => [...new Set(rows.map(row => row[field]).filter(Boolean))].sort((a, b) => a.localeCompare(b));
const option = (value, label, selected) => `<option value="${escape(value)}"${value === selected ? " selected" : ""}>${escape(label)}</option>`;

async function load(slug) {
  if (cache.has(slug)) return cache.get(slug);
  const response = await fetch(`./_data/${slug}.json`);
  if (!response.ok) throw new Error("Local data unavailable");
  const result = await response.json();
  cache.set(slug, result);
  return result;
}

function updateUrl() {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value && !(key === "sort" && value === "newest") && !(key === "page" && value === "1")) query.set(key, value);
  }
  history.replaceState(null, "", `#/${page}${query.size ? `?${query}` : ""}`);
}

function heading(title, description, label = "Austin, Texas") {
  return `<header class="page-heading"><p class="section-label">${label}</p><h1>${title}</h1><p class="page-description">${description}</p></header>`;
}

function renderBrowser() {
  const dataset = DATASETS[page];
  const dates = data.rows.map(row => dateKey(row[dataset.date])).sort();
  const years = [...new Set(dates.map(date => date.slice(0, 4)))].sort().reverse();
  const parties = unique(data.rows, dataset.party);
  const types = page === "contributions" ? unique(data.rows, "contribution_type") : [];
  const mobile = matchMedia("(max-width: 800px)").matches;
  app.innerHTML = `${heading(dataset.title, dataset.description, page === "contributions" ? "Austin, Texas / Campaign finance" : "Austin, Texas / Public spending")}
    <dl class="coverage-strip" aria-label="Dataset coverage">
      <div><dt>${page === "contributions" ? "Contribution records" : "Payment lines"}</dt><dd>${number.format(data.rows.length)}</dd></div>
      <div><dt>${page === "contributions" ? "Reported organization names" : "Vendor"}</dt><dd>${number.format(unique(data.rows, dataset.name).length)}</dd></div>
      <div><dt>${page === "contributions" ? "Contribution dates" : "Payment dates"}</dt><dd class="scope-stat">${prettyDate(dates[0])} – ${prettyDate(dates.at(-1))}</dd></div>
      <div><dt>Snapshot date</dt><dd class="scope-stat">${prettyDate(data.profiled_at)}</dd></div>
    </dl>
    ${page === "payments" ? `<p class="scope-note">Coverage includes one vendor. ${external("https://data.austintexas.gov/d/8c6z-qnmj", "Browse all City payment records")}.</p>` : ""}
    <div class="workspace">
      <aside aria-label="Filter records">
        <details class="filters"${mobile ? "" : " open"}>
          <summary>Filter records</summary>
          <form class="filter-form" id="filter-form" role="search">
            <div class="field"><label for="search">${page === "contributions" ? "Contributor or recipient" : "Vendor or department"}</label>
              <div class="search-box"><input id="search" name="q" type="search" placeholder="Search names…" value="${escape(filters.q)}" autocomplete="off" aria-describedby="search-help">${searchIcon}</div>
              <span class="field-help" id="search-help">${page === "contributions" ? "Try “realtors” or “Watson”" : "Search by name or vendor code"}</span>
            </div>
            <div class="field"><label for="year">${dataset.yearLabel}</label><select id="year" name="year">${option("", "All years", filters.year)}${years.map(year => option(year, year, filters.year)).join("")}</select></div>
            <div class="field"><label for="party">${dataset.partyLabel}</label><select id="party" name="party">${option("", `All ${page === "contributions" ? "recipients" : "departments"}`, filters.party)}${parties.map(party => option(party, party, filters.party)).join("")}</select></div>
            ${page === "contributions" ? `<div class="field"><label for="type">Contribution type</label><select id="type" name="type">${option("", "All types", filters.type)}${types.map(type => option(type, TYPE_LABELS[type] || type, filters.type)).join("")}</select></div>
              <label class="checkbox-field"><input type="checkbox" name="corrections" value="only"${filters.corrections === "only" ? " checked" : ""}>Only records marked as corrections</label>` : ""}
            <button type="reset" class="link-button">Reset filters</button>
          </form>
          <p class="filter-source"><strong>What's included</strong>${page === "contributions" ? "Records classified as ENTITY by the City. Individual donors are excluded. Names are shown as reported." : "Payment lines under vendor AUS6036990. A payment may have multiple accounting lines."}<br><a href="#/about">Coverage &amp; methods →</a></p>
        </details>
      </aside>
      <section class="results" aria-label="Records">
        <div class="results-toolbar">
          <h2 id="result-count" role="status" aria-live="polite" aria-atomic="true"></h2>
          <div class="toolbar-actions"><label class="sort-control" for="sort">Sort <select id="sort" name="sort">${[["newest", "Newest first"], ["oldest", "Oldest first"], ["amount-desc", "Amount: high to low"], ["amount-asc", "Amount: low to high"], ["name", `${dataset.nameLabel}: A–Z`]].map(([value, label]) => option(value, label, filters.sort)).join("")}</select></label>
          <button class="button" id="download" title="Download all records matching the current filters">${downloadIcon} Download CSV</button></div>
        </div>
        <div class="active-filters" id="active-filters" aria-label="Active filters"></div>
        <div id="table-area"></div>
        <p class="table-note">${page === "contributions" ? "Includes monetary, in-kind, and pledged contributions, plus correction records. Rows are not a deduplicated fundraising total." : "Amounts are accounting lines as reported, including adjustments. A line is not necessarily a separate payment."} <a href="#/about">How to read these records</a></p>
        <p class="table-note">Source: ${external(`https://data.austintexas.gov/d/${dataset.id}`, "City of Austin")} <span aria-hidden="true">·</span> Snapshot ${prettyDate(data.profiled_at)} <span aria-hidden="true">·</span> <a href="#/sources">Sources &amp; downloads</a></p>
      </section>
    </div>`;
  const form = document.querySelector("#filter-form");
  const applyFilters = () => {
    const values = Object.fromEntries(new FormData(form));
    filters = { ...values, sort: filters.sort, page: "1" };
    updateUrl();
    renderResults();
  };
  form.addEventListener("submit", event => { event.preventDefault(); clearTimeout(searchTimer); applyFilters(); });
  form.addEventListener("input", event => {
    if (event.target.name !== "q") return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(applyFilters, 140);
  });
  form.addEventListener("change", event => { if (event.target.name !== "q") { clearTimeout(searchTimer); applyFilters(); } });
  form.addEventListener("reset", event => {
    event.preventDefault(); resetFilters();
    document.querySelector(".filters").open = true;
    document.querySelector("#search").focus();
  });
  document.querySelector("#sort").addEventListener("change", event => {
    filters.sort = event.target.value; filters.page = "1"; updateUrl(); renderResults();
  });
  document.querySelector("#download").addEventListener("click", () => download(data, visibleRows, dataset.slug));
  renderResults();
}

function resetFilters() {
  clearTimeout(searchTimer);
  filters = { q: "", year: "", party: "", type: "", corrections: "", sort: "newest", page: "1" };
  updateUrl();
  renderBrowser();
}

function renderResults() {
  const dataset = DATASETS[page];
  visibleRows = filterRows(data.rows, dataset, filters);
  const totalPages = Math.max(1, Math.ceil(visibleRows.length / PAGE_SIZE));
  const currentPage = Math.min(totalPages, Math.max(1, Number.parseInt(filters.page, 10) || 1));
  if (String(currentPage) !== filters.page) { filters.page = String(currentPage); updateUrl(); }
  const start = (currentPage - 1) * PAGE_SIZE;
  const shown = visibleRows.slice(start, start + PAGE_SIZE);
  document.querySelector("#result-count").innerHTML = `<strong>${number.format(visibleRows.length)}</strong> records${visibleRows.length !== data.rows.length ? ` <span class="quiet">of ${number.format(data.rows.length)}</span>` : ""}`;
  document.querySelector("#download").disabled = !visibleRows.length;
  document.querySelector("#active-filters").innerHTML = ["q", "year", "party", "type", "corrections"].filter(key => filters[key]).map(key => {
    const label = key === "q" ? `Search: ${filters.q}` : key === "corrections" ? "Corrections only" : TYPE_LABELS[filters[key]] || filters[key];
    return `<button class="filter-chip" data-remove-filter="${key}" aria-label="${escape(`Remove filter: ${label}`)}">${escape(label)}<span aria-hidden="true">×</span></button>`;
  }).join("");
  document.querySelector("#table-area").innerHTML = visibleRows.length ? `
    <p class="table-scroll-hint">Scroll the table horizontally to see all columns →</p>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Record table; scroll horizontally on smaller screens">
      <table class="records-table"><caption class="visually-hidden">${dataset.title}; ${number.format(visibleRows.length)} matching records. Select a ${dataset.nameLabel.toLowerCase()} to open record details.</caption><thead><tr><th scope="col">Date</th><th scope="col">${dataset.nameLabel}</th><th scope="col">${dataset.partyLabel}</th><th scope="col" class="numeric">Amount</th></tr></thead><tbody>
      ${shown.map((row, index) => `<tr><td class="date-cell">${prettyDate(row[dataset.date])}</td><td><button class="record-link" data-record="${start + index}" aria-label="${escape(`View record: ${row[dataset.name]}, ${prettyDate(row[dataset.date])}, ${currency.format(Number(row[dataset.amount]))}`)}">${escape(row[dataset.name])}</button><span class="row-detail">${escape(page === "contributions" ? TYPE_LABELS[row.contribution_type] || row.contribution_type : row.obj_nm)}</span></td><td>${escape(row[dataset.party] || "Not reported")}</td><td class="numeric">${currency.format(Number(row[dataset.amount]))}${row.correction ? '<span class="correction-label">Correction</span>' : ""}</td></tr>`).join("")}
      </tbody></table>
    </div>
    <div class="pagination"><span>Showing ${number.format(start + 1)}–${number.format(start + shown.length)} of ${number.format(visibleRows.length)}</span><div class="page-buttons"><button class="button" data-pagination="${currentPage - 1}"${currentPage === 1 ? " disabled" : ""}>← Previous</button><span class="page-number">Page ${currentPage} of ${totalPages}</span><button class="button" data-pagination="${currentPage + 1}"${currentPage === totalPages ? " disabled" : ""}>Next →</button></div></div>`
    : `<div class="table-scroll"><div class="empty-state"><h3>No records match these filters</h3><p>Try a shorter name or include more years.</p><button class="link-button" data-reset>Clear all filters</button></div></div>`;
}

function download(sourceData, rows, slug) {
  if (!rows.length) return;
  const blob = new Blob([csvForRows(sourceData.fields, rows)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${slug}-${dateKey(sourceData.profiled_at)}-${rows.length}-records.csv`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showRecord(index) {
  const row = visibleRows[index];
  if (!row) return;
  const dataset = DATASETS[page];
  const facts = [
    [dataset.partyLabel, row[dataset.party] || "Not reported"],
    [page === "contributions" ? "Date contributed" : "Date issued", prettyDate(row[dataset.date])],
    ...(page === "contributions" ? [["Record type", row.contribution_type], ["Donor type", row.donor_type], ["Transaction ID", row.transaction_id], ["Correction flag", row.correction || "Not flagged"]]
      : [["Vendor code", row.vend_cust_cd], ["Fiscal year", row.fy_dc], ["Category", row.obj_nm], ["Payment status", row.cvl_chk_sta_dv], ["Document", `${row.rfed_doc_cd} ${row.rfed_doc_dept_cd} ${row.rfed_doc_id}`], ["Accounting line", row.rfed_actg_ln_no]]),
  ];
  const filing = filingUrl(row.view_report);
  document.querySelector("#record-detail").innerHTML = `<p class="section-label">${dataset.title}</p><h2 id="record-title">${escape(row[dataset.name])}</h2><p class="record-amount">${currency.format(Number(row[dataset.amount]))}</p><dl class="record-facts">${facts.map(([key, value]) => `<div><dt>${key}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>
    ${row.correction ? '<p class="scope-note">The City marks this record as a correction. Earlier and corrected entries may both appear in the source.</p>' : ""}
    <div class="record-source"><h3>Original source</h3><p>${escape(page === "contributions" ? "City of Austin · Campaign Finance – Contributions" : "City of Austin · eCheckbook")}<br>Snapshot ${prettyDate(data.profiled_at)}</p>
    ${filing ? external(filing, "View original filing") : ""}
    ${external(officialRecordUrl(data, row), "View matching City source rows (JSON)")}
    <p>Source links open the City's current records, which may have changed since this snapshot.</p><button class="button" data-download-record="${index}">${downloadIcon} Download this record</button>
    <details><summary>Snapshot reference</summary><p>Source dataset: <code>${data.dataset_id}</code></p><p>SHA-256 of the frozen source CSV:</p><code>${escape(data.sha256)}</code></details></div>`;
  dialog.showModal();
}

const SOURCE_TEXT = {
  "campaign-contributions": ["Campaign contributions", "Contributors, recipients, amounts, and contribution types. The record browser includes organization records only.", "contribution_date"],
  "campaign-reports": ["Campaign reports", "Filing dates, reporting periods, and the totals reported by candidates and committees.", "period_from"],
  "campaign-transactions": ["Campaign transactions", "Itemized contributions, expenditures, loans, and other reported transactions.", "transaction_date"],
  "echeckbook": ["City payments · eCheckbook", "City payment accounting lines by vendor, department, and expense category.", "chk_eft_iss_dt"],
  "contracts": ["City contracts", "Contract descriptions, vendors, purchase limits, and effective dates. A current-only source.", "today"],
  "purchase-orders": ["Purchase orders", "Items purchased, quantities, unit prices, vendors, and order dates.", "award_date"],
};

async function renderSources(version) {
  const [sources, contributions, payments] = await Promise.all([load("sources"), load("campaign-contributions"), load("echeckbook")]);
  if (version !== renderVersion) return;
  app.innerHTML = `${heading("Sources & downloads", "Downloadable extracts and the City datasets they come from.")}
    <div class="source-intro"><h2>Download the records in this browser</h2><p>CSV · Snapshot ${prettyDate(contributions.profiled_at)}</p></div>
    <div class="download-list"><div class="download-item"><div><h3><a href="#/contributions">Organization contributions</a></h3><p>${number.format(contributions.rows.length)} records · All organization contribution types</p></div><button class="button" data-download-source="campaign-contributions">${downloadIcon} CSV</button></div>
    <div class="download-item"><div><h3><a href="#/payments">City payments</a></h3><p>${number.format(payments.rows.length)} lines · Austin Board of REALTORS only</p></div><button class="button" data-download-source="echeckbook">${downloadIcon} CSV</button></div></div>
    <div class="source-intro"><h2>City of Austin source datasets</h2><p>${sources.length} sources · Counts from the frozen snapshots</p></div>
    <div class="table-scroll" tabindex="0" role="region" aria-label="Source dataset table; scroll horizontally on smaller screens"><table class="source-table"><caption class="visually-hidden">Official City source datasets, snapshot row counts, date coverage, and external source downloads.</caption><thead><tr><th scope="col">Dataset</th><th scope="col" class="numeric">Source rows</th><th scope="col">Dates in source</th><th scope="col">Original data</th></tr></thead><tbody>
    ${[...sources].sort((a, b) => Object.keys(SOURCE_TEXT).indexOf(a.slug) - Object.keys(SOURCE_TEXT).indexOf(b.slug)).map(source => {
      const [title, description, dateField] = SOURCE_TEXT[source.slug];
      const range = source.dates[dateField];
      return `<tr><td><h3>${title}</h3><p>${description}</p></td><td class="numeric">${number.format(source.row_count)}</td><td class="source-period">${source.slug === "contracts" ? `${prettyDate(range.max)}<span class="row-detail">Source build date</span>` : `${prettyDate(range.min)}<br>${prettyDate(source.slug === "campaign-reports" ? source.dates.period_to.max : range.max)}`}</td><td class="source-actions">${external(source.url, "City dataset")}${external(source.csv_url, "City CSV")}</td></tr>`;
    }).join("")}</tbody></table></div>
    <p class="source-footnote">Source counts describe the complete City snapshots, not the smaller extracts in this browser. City links open external, current datasets and may contain additional fields. Campaign contributions also appear in campaign transactions; do not add their totals together.</p>
    <p class="source-footnote"><a href="#/about">Read the coverage and calculation notes →</a></p>`;
}

function renderAbout() {
  app.innerHTML = `${heading("About the data", "Coverage, source records, and the limits of this dataset.")}
    <div class="about-layout"><aside class="contents" aria-label="On this page"><h2>On this page</h2><a href="#coverage" data-section="coverage">Coverage</a><a href="#reading" data-section="reading">Reading the records</a><a href="#names" data-section="names">Names and identity</a><a href="#downloads" data-section="downloads">Downloads and reuse</a></aside>
    <div class="prose"><section id="coverage"><h2>Coverage</h2><p>The record browser uses City of Austin CSV snapshots profiled on August 18, 2026. It does not update automatically when the City changes its records.</p>
    <table><caption class="visually-hidden">Local browser coverage</caption><tbody><tr><td>Contributions</td><td>All records marked <code>ENTITY</code> in the contribution snapshot. Individual donors are excluded. The organization names are preserved as reported.</td></tr><tr><td>City payments</td><td>Payment lines for <code>AUS6036990</code>, with the reported vendor name <code>AUSTIN BOARD OF REALTORS</code>. Other City vendors are not included in this extract.</td></tr><tr><td>Other datasets</td><td>The source directory links to campaign reports, transactions, contracts, and purchase orders. These are available from the City; their records are not loaded into this browser.</td></tr></tbody></table></section>
    <section id="reading"><h2>Reading the records</h2><ul><li><strong>A contribution row is a reported entry.</strong> Types include monetary contributions, in-kind support, pledges, and some expenditure records. Use the type filter when comparing amounts.</li><li><strong>Corrections are retained.</strong> A correction flag does not tell us which earlier row to remove. Summing every row can count earlier and corrected entries.</li><li><strong>A payment line is an accounting entry.</strong> Several lines can belong to one payment. Negative amounts and adjustments are preserved.</li><li><strong>The datasets overlap.</strong> Contributions are also represented in the broader campaign transaction source. Adding both sources together would count records twice.</li></ul><p>Dates in the tables describe the transaction or payment. The snapshot date describes when the local source was profiled. Original-source links show the City's current data.</p></section>
    <section id="names"><h2>Names and identity</h2><p>Names are displayed as the City reported them. A count of reported organization names is not a count of distinct legal organizations: spelling differences can produce multiple names.</p><p>A matching name in contribution and payment data does not establish that the records refer to the same legal organization. Cross-source identity has not been verified. These records alone do not establish influence or wrongdoing.</p></section>
    <section id="downloads"><h2>Downloads and reuse</h2><p>CSV exports contain all records matching your filters, across every page. Source field names and reported amounts are preserved. Direct contact and address fields are excluded. Spreadsheet formula-like text is escaped with a leading apostrophe.</p><p>Record details include the source dataset ID and the SHA-256 checksum of the original frozen CSV. When citing this extract, include the dataset name, snapshot date, and any filters you applied.</p><p>Data in this browser can be inspected and downloaded without an account. The ${external("https://github.com/joshcazalas/money-on-record", "project source code")} is available on GitHub. For the original records and the City's reuse terms, visit the ${external("https://data.austintexas.gov/", "City of Austin open data portal")}.</p></section></div></div>`;
}

async function renderRoute() {
  clearTimeout(searchTimer);
  const version = ++renderVersion;
  const hash = location.hash.replace(/^#\/?/, "");
  const [requested, query] = hash.split("?");
  page = ["contributions", "payments", "sources", "about"].includes(requested) ? requested : "contributions";
  filters = { q: "", year: "", party: "", type: "", corrections: "", sort: "newest", page: "1" };
  const params = new URLSearchParams(query);
  for (const key of Object.keys(filters)) if (params.has(key)) filters[key] = params.get(key);
  if (!["newest", "oldest", "amount-desc", "amount-asc", "name"].includes(filters.sort)) filters.sort = "newest";
  dialog.close();
  document.querySelectorAll("[data-page]").forEach(link => {
    if (link.dataset.page === page) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  document.title = `${DATASETS[page]?.title || (page === "sources" ? "Sources & downloads" : "About the data")} · Money on Record`;
  try {
    if (DATASETS[page]) {
      const result = await load(DATASETS[page].slug);
      if (version !== renderVersion) return;
      data = result;
      renderBrowser();
    } else if (page === "sources") await renderSources(version);
    else renderAbout();
  } catch {
    if (version !== renderVersion) return;
    app.innerHTML = `${heading("Records could not be loaded", "Try again in a moment, or use the original City datasets.")}<p>${external("https://data.austintexas.gov/", "Browse the City of Austin open data portal")}</p><button class="button" data-retry>Try again</button>`;
  }
}

app.addEventListener("click", async event => {
  const target = event.target.closest("button, a");
  if (!target) return;
  if (target.hasAttribute("data-record")) showRecord(Number(target.dataset.record));
  if (target.hasAttribute("data-pagination")) {
    filters.page = target.dataset.pagination; updateUrl(); renderResults();
    document.querySelector(".results-toolbar").scrollIntoView({ block: "start" });
    document.querySelector(".table-scroll").focus({ preventScroll: true });
  }
  if (target.hasAttribute("data-reset")) { resetFilters(); document.querySelector(".filters").open = true; document.querySelector("#search").focus(); }
  if (target.hasAttribute("data-remove-filter")) {
    const key = target.dataset.removeFilter;
    filters[key] = ""; filters.page = "1";
    const control = document.querySelector(`[name="${key}"]`);
    if (control.type === "checkbox") control.checked = false; else control.value = "";
    updateUrl(); renderResults();
    document.querySelector(".filters").open = true;
    control.focus();
  }
  if (target.hasAttribute("data-download-source")) {
    const source = await load(target.dataset.downloadSource);
    download(source, source.rows, target.dataset.downloadSource);
  }
  if (target.hasAttribute("data-retry")) renderRoute();
  if (target.hasAttribute("data-section")) {
    event.preventDefault(); document.getElementById(target.dataset.section).scrollIntoView();
  }
});
dialog.addEventListener("click", event => {
  const button = event.target.closest("[data-download-record]");
  if (button) download(data, [visibleRows[Number(button.dataset.downloadRecord)]], DATASETS[page].slug);
  if (event.target === dialog && event.clientX < dialog.getBoundingClientRect().left) dialog.close();
});
window.addEventListener("hashchange", () => { renderRoute(); window.scrollTo(0, 0); });
document.querySelector(".skip-link").addEventListener("click", event => {
  event.preventDefault();
  document.querySelector("#content").focus();
  document.querySelector("#content").scrollIntoView();
});
renderRoute();
