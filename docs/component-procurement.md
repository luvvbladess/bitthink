# Component sourcing and procurement plan

The marketplaces skill includes a component/BOM workflow. The planner allocates
specialist suppliers separately from general marketplaces, passes exact MPNs,
packages and quantities, and asks employees to verify stock on product pages.
It distinguishes own stock, supplier stock, backorders, partial quantities,
MOQ/pack multiples, warehouse lead time and delivery to the requested city.
Unknown values remain unknown; analogues never silently fulfill an exact MPN.

The existing document and spreadsheet tools read the specification and produce
the CSV/XLSX procurement plan. Large specifications should be processed in
batches with explicit input/checked/covered/unprocessed counts. A completed
300-line BOM run has not yet been validated. The skill is an agent workflow,
not a deterministic inventory database or a global cost optimizer.

The backend and ordinary-browser extension allow public product cards on
chipdip.ru, terraelectronica.ru, promelec.ru, compel.ru and platan.ru, in addition
to the existing marketplaces. Reinstall/reload extension version 1.1.0 and grant
the added host permissions before expecting home-browser reads on those sites.
Unknown stores retain the existing server reader/search fallback. Browser
stock/lead-time passages are placed before lengthy descriptions so the scraper's
text limit does not remove all commercial conditions.

Current scope, confirmed by the user: search and procurement plan only. Real
carts, account registration, stock reservations, orders and payment links are a
later phase. Product links must not be described as prepared carts.

Future carts require store-specific connectors, explicit account/session access,
idempotent cart updates, a final SKU/quantity/pack/price review and revalidation
at checkout. Creating a basket must not silently submit a paid order. The current
reader does not perform these actions.

Validation: 56 relevant backend tests passed, including component-triggered skill
selection and relay delivery for a specialist-store URL. Extension tests verify
store URL guards, private-page rejection, preservation of stock passages before
15K clipping and tab cleanup. A Chromium fixture verifies the MV3 worker and
description/specification/review collection; real inventory and destination-
specific delivery must still be checked on actual supplier pages.
