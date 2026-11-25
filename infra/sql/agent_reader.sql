-- Run once as the Entra SQL admin, after `procurement-agent ingest-data` has created the views.
-- Replace <app-name> with the web app name output by main.bicep (its managed identity's name).
--
-- The agent identity can SELECT from the three approved views and nothing else: no base table,
-- no write permissions. This is the database-side half of the "approved views only" control;
-- the MCP tools enforce the other half in code.

CREATE USER [<app-name>] FROM EXTERNAL PROVIDER;

GRANT SELECT ON OBJECT::dbo.v_contracts      TO [<app-name>];
GRANT SELECT ON OBJECT::dbo.v_vendor_summary TO [<app-name>];
GRANT SELECT ON OBJECT::dbo.v_spend_by_year  TO [<app-name>];

-- Explicitly deny the base table in case broader grants are added later.
DENY SELECT ON OBJECT::dbo.contracts TO [<app-name>];
