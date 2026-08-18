# Campaign Finance - Report Detail

- Dataset ID: `b2pc-2s8n`
- Role: `canonical`
- Frozen metadata: `data/metadata/b2pc-2s8n/089384ba62550e190741ec048c21e8cc33b0b8b65118510738eef8a4759adcb2.json`
- Publication rule: default deny; only `PUBLIC_ALLOWLISTED` fields may leave the pipeline.

## Fields

| API field | Display name | Socrata type | Classification | Description |
|---|---|---|---|---|
| `filer_name` | Filer_Name | `text` | `PUBLIC_ALLOWLISTED` | Name of individual, committee, or entity filing the report. This name is a standardized format used by the Office of the City Clerk to ensure all of a filer's reports are accessible under a single name |
| `form_type` | Form | `text` | `PUBLIC_ALLOWLISTED` | The type of form filed. |
| `report_type` | Report_Type | `text` | `PUBLIC_ALLOWLISTED` | The primary report type as listed on the form. |
| `report_type2` | Report_Type2 | `text` | `PUBLIC_ALLOWLISTED` | Secondary report type as listed on the form submitted, if applicable. |
| `link_to_report` | View_Report | `url` | `PUBLIC_ALLOWLISTED` | A link to view a PDF version of the report filed with the Office of the City Clerk. |
| `date_filed` | Date_Filed | `calendar_date` | `PUBLIC_ALLOWLISTED` | Date the structured data file was received by the Office of the City Clerk |
| `filer_address_2` | Filer_Address | `text` | `RESTRICTED` | The filer's street or mailing address. |
| `filer_city` | Filer_City_State_Zip | `text` | `RESTRICTED` | The filer’s city. |
| `report_id` | Report_ID | `text` | `PUBLIC_ALLOWLISTED` | Unique identifier for the specific report - can be used to link individual transactions to a specific report. |
| `treasurer_name` | Treasurer_Name | `text` | `RESTRICTED` | Name of the filer's campaign treasurer as listed on the report filed with the Office of the City Clerk. |
| `treasurer_address_2` | Treasurer_Address | `text` | `RESTRICTED` | Address of the filer's campaign treasurer. |
| `treasurer_city_state_zip` | Treasurer_City_State_Zip | `text` | `RESTRICTED` | City of the filer’s campaign treasurer. |
| `date_due` | Date_Due | `calendar_date` | `PUBLIC_ALLOWLISTED` | Due date of the report, if applicable. |
| `name_as_reported` | Name_as_Reported | `text` | `INTERNAL_REVIEW` | Name of the filer, committee, or entity as listed on the report filed with the Office of the City Clerk. |
| `filer_phone` | Filer_Phone | `text` | `RESTRICTED` | The filer’s area code, phone number, and (if applicable) extension. |
| `treasurer_state` | Treasurer_State | `text` | `RESTRICTED` | State of the filer’s campaign treasurer. |
| `treasurer_zip_code` | Treasurer_Zip_Code | `text` | `RESTRICTED` | Zip code of the filer’s campaign treasurer. |
| `treasurer_phone` | Treasurer_Phone | `text` | `RESTRICTED` | The area code, phone number and (if applicable) extension of the filer’s campaign treasurer |
| `period_from` | Period_From | `calendar_date` | `PUBLIC_ALLOWLISTED` | The date on which the reporting period for this report starts.  |
| `period_to` | Period_To | `calendar_date` | `PUBLIC_ALLOWLISTED` | The date on which the reporting period for this report ends, if applicable.  For  the ATX 1, this field corresponds to the report date listed on the form. |
| `election_date` | Election_Date | `calendar_date` | `PUBLIC_ALLOWLISTED` | The date of the election for which this report is filed, if applicable |
| `election_type` | Election_Type | `text` | `PUBLIC_ALLOWLISTED` | The type of the election for which this report is filed, if applicable |
| `office_held` | Office_Held | `text` | `PUBLIC_ALLOWLISTED` | For officeholders, the office currently held. |
| `office_sought` | Office_Sought | `text` | `PUBLIC_ALLOWLISTED` | For candidates in an upcoming election, the office being sought. For unsuccessful candidates in a recently held election, the office sought during the election preceding the deadline for this report. |
| `unitemized_contrib_total` | Unitemized_Contrib_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized contributions received by the filer during the reporting period  |
| `contrib_total` | Contrib_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all contributions received by the filer during the reporting period (itemized and unitemized)  |
| `unitemized_expend_total` | Unitemized_Expend_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized expenditures made by the filer during the reporting period  |
| `expend_total` | Expend_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all expenditures made by the filer during the reporting period (itemized and unitemized)  |
| `contrib_balance` | Contrib_Balance | `number` | `PUBLIC_ALLOWLISTED` | The total of all political contributions, including interest and additional income, as of the last day of the reporting period  |
| `outstand_loan` | Outstand_Loan | `number` | `PUBLIC_ALLOWLISTED` | Outstanding principal of all loans maintained as of the last day of the reporting period  |
| `unitemized_inkind_total` | Unitemized_InKind_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized in-kind contributions received by the filer during the reporting period  |
| `unitemized_pledge_total` | Unitemized_Pledge_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized pledges received by the filer during the reporting period  |
| `unitemized_loan_total` | Unitemized_Loan_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized loans maintained by the filer during the reporting period  |
| `unitemized_unpaid_total` | Unitemized_Unpaid_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized unpaid obligations incurred by the filer during the reporting period  |
| `unitemized_cred_card_total` | Unitemized_Cred_Card_Total | `number` | `PUBLIC_ALLOWLISTED` | The total of all unitemized credit card expenditures made by the filer during the reporting period  |
