import test from "node:test";
import assert from "node:assert/strict";
import { DATASETS, filterRows, csvForRows, officialRecordUrl, filingUrl } from "../frontend/data.js";

const rows = [
  { transaction_id: "101", donor: "Example Association", recipient: "Committee A", contribution_date: "12/31/2023", contribution_amount: "900.00", contribution_type: "Contribution", correction: "" },
  { transaction_id: "102", donor: "EXAMPLE Association", recipient: "Committee B", contribution_date: "01/02/2024", contribution_amount: "1000.50", contribution_type: "Pledged Contribution", correction: "X" },
  { transaction_id: "103", donor: "Another Organization", recipient: "Committee B", contribution_date: "01/01/2024", contribution_amount: "-20.00", contribution_type: "Contribution", correction: "" },
];

test("search is case insensitive and combines with year, recipient, type, and correction filters", () => {
  const filtered = filterRows(rows, DATASETS.contributions, {
    q: "  example committee B  ", year: "2024", party: "Committee B",
    type: "Pledged Contribution", corrections: "only",
  });
  assert.deepEqual(filtered.map(row => row.transaction_id), ["102"]);
  assert.equal(filterRows(rows, DATASETS.contributions, { q: "missing" }).length, 0);
  assert.equal(filterRows(rows, DATASETS.contributions, { year: "2022" }).length, 0);
});

test("dates sort chronologically across years without mutating source rows", () => {
  assert.deepEqual(filterRows(rows, DATASETS.contributions, { sort: "newest" }).map(row => row.transaction_id), ["102", "103", "101"]);
  assert.deepEqual(filterRows(rows, DATASETS.contributions, { sort: "oldest" }).map(row => row.transaction_id), ["101", "103", "102"]);
  assert.deepEqual(rows.map(row => row.transaction_id), ["101", "102", "103"]);
});

test("amount sort is numeric and preserves negative adjustments", () => {
  assert.deepEqual(filterRows(rows, DATASETS.contributions, { sort: "amount-desc" }).map(row => row.contribution_amount), ["1000.50", "900.00", "-20.00"]);
  assert.deepEqual(filterRows(rows, DATASETS.contributions, { sort: "amount-asc" }).map(row => row.contribution_amount), ["-20.00", "900.00", "1000.50"]);
});

test("payment search accepts vendor codes and department names", () => {
  const payments = [{ vend_cust_cd: "ORG123", lgl_nm: "Example Organization", dept_nm: "Library", chk_eft_iss_dt: "03/04/2020", amount: "12.34" }];
  assert.equal(filterRows(payments, DATASETS.payments, { q: "org123 library", year: "2020" }).length, 1);
  assert.equal(filterRows(payments, DATASETS.payments, { party: "Parks" }).length, 0);
});

test("CSV preserves commas, quotes, newlines, and decimal strings, and neutralizes formulas", () => {
  const csv = csvForRows(["donor", "amount"], [
    { donor: 'Example, "Organization"\nBranch', amount: "-20.00" },
    { donor: "=HYPERLINK(1)", amount: "1000.50" },
    { donor: " +SUM(1)", amount: "0.00" },
  ]);
  assert.equal(csv, '\uFEFF"donor","amount"\r\n"Example, ""Organization""\nBranch","-20.00"\r\n"\'=HYPERLINK(1)","1000.50"\r\n"\' +SUM(1)","0.00"\r\n');
});

test("official record links include only selected fields and quote identifier values", () => {
  const url = new URL(officialRecordUrl({ dataset_id: "3kfv-biw6", fields: ["transaction_id", "donor"] }, { transaction_id: "a'b" }));
  assert.equal(url.hostname, "data.austintexas.gov");
  assert.equal(url.searchParams.get("$select"), "transaction_id,donor");
  assert.equal(url.searchParams.get("$where"), "transaction_id = 'a''b'");
});

test("filing links accept the City report format and reject unrelated or executable URLs", () => {
  assert.equal(filingUrl("View Report (https://services.austintexas.gov/edims/document.cfm?id=123)"), "https://services.austintexas.gov/edims/document.cfm?id=123");
  assert.equal(filingUrl("javascript:alert(1)"), null);
  assert.equal(filingUrl("https://services.austintexas.gov.attacker.example/report"), null);
  assert.equal(filingUrl(""), null);
});
