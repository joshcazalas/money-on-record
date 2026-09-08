export const DATASETS = {
  contributions: {
    slug: "campaign-contributions", id: "3kfv-biw6", title: "Campaign contributions",
    description: "Contributions reported by organizations to Austin candidates and political committees.",
    name: "donor", party: "recipient", date: "contribution_date", amount: "contribution_amount",
    partyLabel: "Recipient", nameLabel: "Contributor", yearLabel: "Contribution year",
  },
  payments: {
    slug: "echeckbook", id: "8c6z-qnmj", title: "City payments",
    description: "City of Austin payment lines for Austin Board of REALTORS, vendor AUS6036990.",
    name: "lgl_nm", party: "dept_nm", date: "chk_eft_iss_dt", amount: "amount",
    partyLabel: "Department", nameLabel: "Vendor", yearLabel: "Payment year",
  },
};

export const TYPE_LABELS = {
  "Contribution": "Contribution",
  "Monetary Political Contribution": "Monetary",
  "Monetary Contribution From Corporation Or Labor Organization": "Corporate / labor contribution",
  "Monetary Support From Corporation Or Labor Organization": "Corporate / labor support",
  "Non-Monetary Support From Corporation Or Labor Organization": "In-kind corporate / labor support",
  "Non-Monetary (In-Kind) Political Contribution": "In-kind",
  "Non-Monetary (In-Kind) Contribution From Corporation Or Labor Organization": "In-kind corporate / labor contribution",
  "Pledged Contribution": "Pledge",
  "Pledged Contribution From Corporation Or Labor Organization": "Corporate / labor pledge",
  "Political Expenditures From Political Contribution": "Political expenditure",
};

export function dateKey(value = "") {
  const match = value.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
  return match ? `${match[3]}-${match[1]}-${match[2]}` : value.slice(0, 10);
}

export function filterRows(rows, dataset, filters) {
  const words = (filters.q || "").trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const filtered = rows.filter(row => {
    const searchable = [row[dataset.name], row[dataset.party], row.transaction_id, row.vend_cust_cd]
      .filter(Boolean).join(" ").toLocaleLowerCase();
    return words.every(word => searchable.includes(word))
      && (!filters.year || dateKey(row[dataset.date]).slice(0, 4) === filters.year)
      && (!filters.party || row[dataset.party] === filters.party)
      && (!filters.type || row.contribution_type === filters.type)
      && (filters.corrections !== "only" || Boolean(row.correction));
  });
  return filtered.sort((a, b) => {
    if (filters.sort === "amount-desc") return Number(b[dataset.amount]) - Number(a[dataset.amount]);
    if (filters.sort === "amount-asc") return Number(a[dataset.amount]) - Number(b[dataset.amount]);
    if (filters.sort === "name") return a[dataset.name].localeCompare(b[dataset.name]);
    const direction = filters.sort === "oldest" ? 1 : -1;
    return direction * dateKey(a[dataset.date]).localeCompare(dateKey(b[dataset.date]));
  });
}

export function csvForRows(fields, rows) {
  const cell = (value, field) => {
    let text = String(value ?? "");
    const numericAmount = ["amount", "contribution_amount"].includes(field) && /^-?\d+(\.\d+)?$/.test(text);
    // Preserve source text while preventing spreadsheet formula execution on export.
    if (!numericAmount && /^[\s]*[=+\-@\t\r]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  return "\uFEFF" + [fields.map(field => cell(field, "")).join(","),
    ...rows.map(row => fields.map(field => cell(row[field], field)).join(","))].join("\r\n") + "\r\n";
}

export function officialRecordUrl(data, row) {
  const fields = data.dataset_id === "3kfv-biw6" ? ["transaction_id"] : [
    "vend_cust_cd", "rfed_doc_cd", "rfed_doc_dept_cd", "rfed_doc_id",
    "rfed_vend_ln_no", "rfed_comm_ln_no", "rfed_actg_ln_no",
  ];
  const where = fields.map(field => `${field} = '${String(row[field]).replaceAll("'", "''")}'`).join(" AND ");
  const query = new URLSearchParams({ "$select": data.fields.join(","), "$where": where, "$limit": "1000" });
  return `https://data.austintexas.gov/resource/${data.dataset_id}.json?${query}`;
}

export function filingUrl(value = "") {
  const match = value.match(/https:\/\/services\.austintexas\.gov\/[^\s)]+/);
  return match ? match[0] : null;
}
