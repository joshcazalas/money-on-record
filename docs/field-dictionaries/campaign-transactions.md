# Campaign Finance - Transaction Detail

- Dataset ID: `g4yx-aw9r`
- Role: `canonical`
- Frozen metadata: `data/metadata/g4yx-aw9r/de9e66abac77aad4e17efbddfff260d30887b3ee8fca674b93556297bdb66b0d.json`
- Publication rule: default deny; only `PUBLIC_ALLOWLISTED` fields may leave the pipeline.

## Fields

| API field | Display name | Socrata type | Classification | Description |
|---|---|---|---|---|
| `transaction_type` | Transaction_Type | `text` | `PUBLIC_ALLOWLISTED` | Identifies the type of transaction reported: Loan, Expenditure, Credit, Pledge, or Contribution. |
| `filer_name` | Filer_Name | `text` | `PUBLIC_ALLOWLISTED` | Name of individual, committee or entity filing the report. This name is a standardized format used by the Office of the City Clerk to ensure all of a filer's reports are accessible under a single name  |
| `transactor_name` | Transactor_Name | `text` | `PUBLIC_ALLOWLISTED` | The transactor's name (for individuals) or the name of the company, political committee, organization, or group (for entities). |
| `entity` | Entity | `text` | `PUBLIC_ALLOWLISTED` | Identifies the transactor as either an entity (such as a company, political committee, organization, or other group) or an individual person |
| `transaction_amount` | Transaction_Amount | `number` | `PUBLIC_ALLOWLISTED` | Amount involved in the transaction. Amounts will be listed as a negative (-) for expenditures. |
| `date_filed` | Date_Filed | `calendar_date` | `PUBLIC_ALLOWLISTED` | Date the structured data file was received by the Office of the City Clerk  |
| `form` | Form | `text` | `PUBLIC_ALLOWLISTED` | The type of form filed |
| `report_id` | Report | `text` | `PUBLIC_ALLOWLISTED` | Unique identifier for the specific report - can be used to link individual transactions to a specific report. |
| `transaction` | Transaction_Code | `text` | `PUBLIC_ALLOWLISTED` | Unique identifier for the individual transaction listed - can be used to link transactions associated with multiple records, e.g. Direct Campaign Expenditures or Out of State Travel |
| `transaction_id` | Transaction_ID | `text` | `PUBLIC_ALLOWLISTED` | Unique ID based upon the concatenation of the Report_ID and Transaction_ID field - acts as a unique key for each individual transaction |
| `date_due` | Date_Due | `calendar_date` | `PUBLIC_ALLOWLISTED` | Due date of the report  |
| `report_type` | Report_Type | `text` | `PUBLIC_ALLOWLISTED` | The primary report type as listed on the form.  |
| `election_date` | Election_Date | `calendar_date` | `PUBLIC_ALLOWLISTED` | The date of the election for which this report is filed, if applicable |
| `election_type` | Election_Type | `text` | `PUBLIC_ALLOWLISTED` | The type of the election for which this report is filed, if applicable |
| `office_held` | Office_Held | `text` | `PUBLIC_ALLOWLISTED` | For officeholders, the office currently held |
| `office_sought` | Office_Sought | `text` | `PUBLIC_ALLOWLISTED` | For candidates in an upcoming election, the office being sought. For unsuccessful candidates in a recently held election, the office sought during the election preceding the deadline for this report |
| `link_to_report` | View_Report | `url` | `PUBLIC_ALLOWLISTED` | A link to view a pdf version of the report on which the transaction is listed |
| `cor_flag` | Correction_Flag | `text` | `PUBLIC_ALLOWLISTED` | If the transaction is reported on a Correction Affidavit, the correction flag will contain either NEW, or MODIFY.    NEW indicates the transaction is newly reported,   MODIFY indicates the transaction is a modification of a previously reported transaction. |
| `schedule_reported` | Schedule_Reported | `text` | `PUBLIC_ALLOWLISTED` | Identifies the TEC Schedule or ATX form on which the transaction is listed |
| `transactor_address_2` | Transactor_Address | `text` | `RESTRICTED` | Address of the individual or entity involved in the transaction. |
| `transactor_city` | Transactor_City_State_Zip | `text` | `RESTRICTED` | City of the individual or entity involved in the transaction. |
| `transactor_state` | Transactor_State | `text` | `RESTRICTED` | State of the individual or entity involved in the transaction. |
| `transactor_zip_code` | Transactor_Zip_Code | `text` | `RESTRICTED` | Zip code of the individual or entity involved in the transaction. |
| `transaction_date` | Transaction_Date | `calendar_date` | `PUBLIC_ALLOWLISTED` | Date on which the transaction occurred. |
| `transaction_description` | Transaction_Description | `text` | `PUBLIC_ALLOWLISTED` | For credits, expenditures, and contributions, a brief description of the transaction.  For in-kind contributions, a description of the contribution or item. For credits, a description of the purpose for which the amount was received. For expenditures, a description of the activity conducted by making the expenditure. |
| `expense_description` | Expense_Description | `text` | `PUBLIC_ALLOWLISTED` | If the transaction is an expenditure, a category and brief description of the purpose of the expenditure reported. |
| `transactor_employer` | Transactor_Employer | `text` | `RESTRICTED` | The transactor's employer (for individuals) |
| `transactor_occupation` | Transactor_Occupation | `text` | `RESTRICTED` | The transactor's occupation (for individuals) |
| `lender_institution` | Financial_Institution | `text` | `PUBLIC_ALLOWLISTED` | For loans, if the lender is a financial institution, this field is marked ‘Y.’ This field is marked ‘N’ for any other type of lender. |
| `interest_rate` | Interest_Rate | `text` | `PUBLIC_ALLOWLISTED` | For loans, the interest rate of the loan. |
| `maturity_date` | Maturity_Date | `calendar_date` | `PUBLIC_ALLOWLISTED` | For loans, the final maturity date of the loan. |
| `collateral` | Collateral | `text` | `PUBLIC_ALLOWLISTED` | For loans, a description of the collateral, if applicable |
| `personal_funds_deposited` | Personal_Funds | `text` | `PUBLIC_ALLOWLISTED` | When marked ’X,‘ indicates that the loan is a deposit of personal funds into an account in which political contributions are held. |
| `guarantor` | Guarantor | `text` | `INTERNAL_REVIEW` | For loans, if there is a guarantor, this field will be marked ‘Y.’ When this is marked ‘N,’ it indicates that there is no guarantor for the loan. |
| `guarantor_name` | Guarantor_Name | `text` | `RESTRICTED` | For loans, the name of the guarantor, if applicable. |
| `guarantor_address_2` | Guarantor_Address | `text` | `RESTRICTED` | For loans, the address of the guarantor, if applicable. |
| `guarantor_city` | Guarantor_City_State_Zip | `text` | `RESTRICTED` | For loans, the city of the guarantor, if applicable. |
| `amount_guaranteed` | Amount_Guaranteed | `number` | `PUBLIC_ALLOWLISTED` | For loans, the amount guaranteed by the guarantor, if applicable. |
| `guarantor_employer` | Guarantor_Employer | `text` | `RESTRICTED` | For loans, the employer of the guarantor, if applicable. |
| `guarantor_occupation` | Guarantor_Occupation | `text` | `RESTRICTED` | For loans, the occupation of the guarantor, if applicable. |
| `outside_travel` | Travel_Outside_Texas | `text` | `PUBLIC_ALLOWLISTED` | When marked ‘X,’ indicates that a transaction is for travel outside the state of Texas.  |
| `political_obligation` | Political_Obligation | `text` | `PUBLIC_ALLOWLISTED` | For an unpaid incurred obligation reported on F2, or a credit card expenditure reported on F4, ’Y’ indicates  the expenditure was political. |
| `reimbursement_intended` | Reimbursement_Intended | `text` | `PUBLIC_ALLOWLISTED` | If the filer intends to be reimbursed for this expenditure, this field will be marked ‘Y.’ |
| `returned_to_filer` | Returned_to_Filer | `text` | `PUBLIC_ALLOWLISTED` | If the transaction was a political contribution returned to the filer, this field will be marked ‘Y.’ |
| `out_of_state_pac` | Out_Of_State_PAC | `text` | `PUBLIC_ALLOWLISTED` | For contributions, pledges, or loans, if the contributor or lender is an out-of-state political committee (PAC), this field will be marked ‘Y.’  |
| `out_of_state_pac_id` | Out_of_State_PAC_ID | `text` | `PUBLIC_ALLOWLISTED` | For contributions, pledges, or loans, if the contributor or lender is an out-of-state political committee (PAC), the committee's Federal Election Commission (FEC) identification number.  |
