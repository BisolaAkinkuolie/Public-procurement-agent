-- Approved views. These are the ONLY objects the agent's MCP tools can read.
--
-- Written in portable SQL (no dialect date functions) so the same file runs on SQLite locally
-- and on Azure SQL. Everything dialect-specific (year extraction, value cleaning, vendor-name
-- normalisation) happens once at ingest time instead.
--
-- Deliberately NOT exposed: vendor_postal_code and former_public_servant (fields that can relate
-- to identifiable individuals), French free-text columns, and standing-offer agreement rows
-- (instrument_type = 'SOSA'), which describe an agreement rather than money spent.

DROP VIEW IF EXISTS v_contracts;
CREATE VIEW v_contracts AS
SELECT
    reference_number,
    procurement_id,
    vendor_name,
    vendor_key,
    department,
    contract_date,
    contract_year,
    description_en,
    commodity_type,
    economic_object_code,
    solicitation_procedure,
    instrument_type,
    number_of_bids,
    contract_value,
    original_value,
    amendment_value,
    committed_value,
    country_of_vendor
FROM contracts
WHERE instrument_type IS NULL OR instrument_type <> 'SOSA';

DROP VIEW IF EXISTS v_vendor_summary;
CREATE VIEW v_vendor_summary AS
SELECT
    vendor_key,
    MAX(vendor_name)            AS vendor_name,
    COUNT(*)                    AS transaction_count,
    SUM(committed_value)        AS committed_value,
    MIN(contract_date)          AS first_contract_date,
    MAX(contract_date)          AS last_contract_date,
    COUNT(DISTINCT department)  AS department_count
FROM contracts
WHERE instrument_type IS NULL OR instrument_type <> 'SOSA'
GROUP BY vendor_key;

DROP VIEW IF EXISTS v_spend_by_year;
CREATE VIEW v_spend_by_year AS
SELECT
    contract_year,
    department,
    commodity_type,
    solicitation_procedure,
    COUNT(*)              AS transaction_count,
    SUM(committed_value)  AS committed_value
FROM contracts
WHERE instrument_type IS NULL OR instrument_type <> 'SOSA'
GROUP BY contract_year, department, commodity_type, solicitation_procedure;
