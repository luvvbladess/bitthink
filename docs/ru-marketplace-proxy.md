# Russian marketplace page routing

Production route: `browse_page` and URL pre-reading -> `web_scraper` -> authenticated HTTP CONNECT proxy through a persistent SSH tunnel -> Russian server -> marketplace.

On the Russian server, `bitthink-ru-proxy.service` runs Tinyproxy bound to `127.0.0.1:18128`. On the application server, `bitthink-ru-tunnel.service` binds to the existing application Docker bridge gateway (`172.18.0.1:18128`). An additional UFW rule permits only that bridge/subnet to reach the listener. No public proxy port is opened. The SSH key allows forwarding only to the RU proxy, from the application server IP; it does not allow shell sessions.

Credentials remain in `/opt/gpt-ultra-web/.env` on the application server and `/etc/bitthink-ru-proxy/tinyproxy.conf` on the Russian server. Never copy them into browser code, source control, logs or deployment archives. `ruserv.txt` and `serv.txt` are local ignored access files.

Russian marketplace links use the proxy first. Other pages retain direct fetching. Tunnel errors trigger the existing direct fallback and cooldown. An actual marketplace block triggers an explicitly labelled search-index fallback. JSON-LD product data (including offers and ratings) is retained before scripts are removed. This fetcher does not execute JavaScript or solve CAPTCHA; proxy connectivity alone does not guarantee access to a product page.

At installation, the proxy exit IP was verified from the production backend container. Ozon, Wildberries, Yandex Market, DNS and Citilink returned anti-bot responses. M.Video returned an HTML shell with no readable body. Do not present these results as successful product-page reads.

## Operations

Check `systemctl status bitthink-ru-proxy` on the RU server and `systemctl status bitthink-ru-tunnel` on the application server. Both services auto-start at boot and restart after failure. The existing Compose network must remain available at its current gateway; if that network is recreated, update the tunnel bind address, scoped UFW rule and `RU_PROXY_URL` together.

Backups are under `/root/bitthink-proxy-backup/` on each server. The application server contains `application.before.tar.gz`, `env.before`, `backend-image.before`, and `release-path`. Existing Nginx/Xray configuration and process IDs are recorded for comparison. Runtime databases, uploads, workspaces, VPN and unrelated sites are not part of application replacement.

To revert the application, restore the application archive under `/opt/gpt-ultra-web`, restore `.env` from `env.before`, tag the saved backend image named in `backend-image.before` as the Compose backend image, then recreate only `backend` and `frontend` with `docker compose up -d --no-deps`. Do not use `docker compose down`, prune Docker, restore entire firewall files, or restart VPN/Nginx for this change. Disabling the two new proxy services is independent of the existing services. The bridge-specific UFW rule can be removed by its exact matching rule.

A final Chromium test was also run directly on the Russian server in a temporary isolated container: Ozon returned 403, Wildberries returned a 498 browser-check page, Yandex Market returned 403 for the IP, and M.Video returned 403 for automated access. The temporary container and its image were removed. A browser renderer was not added to production because this test did not retrieve product content.

Validation: 52 relevant tests passed locally and in the deployed backend with an isolated temporary SQLite database; the production health endpoint and RU exit/authentication checks passed. Existing Nginx and Xray configuration hashes and process IDs remained identical on both servers. Other website endpoints returned successful responses or redirects. Database, sandbox, OnlyOffice and Portainer containers were not recreated.
