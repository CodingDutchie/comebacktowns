#!/usr/bin/env bash
# The publish stage, ported from .github/workflows/publish.yml: export D1 -> site/data, build
# the site, deploy the site + API Worker, purge the API's KV index, smoke-check the live domain.
# Run inside the refresh container (cwd /app). Secrets come from the environment only.
set -euo pipefail
cd /app

python -m pipeline.cli export

(cd site && npm run check && npm run build)

wrangler deploy

ns=$(python3 -c "import tomllib; print([k for k in tomllib.load(open('wrangler.toml','rb'))['kv_namespaces'] if k['binding']=='CACHE'][0]['id'])")
wrangler kv key delete --namespace-id "$ns" --remote "index:v3" || echo "index key not present"

domain=$(python3 -c "import yaml; print(yaml.safe_load(open('config/site.yml'))['SITE_DOMAIN'])")
for path in / /town/catskill-ny /region/hudson-valley /county/greene-county /rankings/most-affordable /methodology /robots.txt /llms.txt /sitemap-index.xml /api/health; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" "https://$domain$path")
  echo "$path -> $code"
  [ "$code" = "200" ] || { echo "smoke check failed: https://$domain$path returned $code"; exit 1; }
done
curl -sS "https://$domain/api/health"; echo

token=$(python3 -c "import yaml; print(yaml.safe_load(open('config/site.yml')).get('ANALYTICS_TOKEN') or '')")
if [ -n "$token" ]; then
  # Save the page then grep it (grep -q closing a pipe would make curl fail under pipefail).
  # The unique query string skips the edge cache, which can briefly hold the previous deploy.
  for attempt in 1 2 3 4 5; do
    curl -sS -A "Mozilla/5.0 (smoke check)" -o /tmp/smoke-home.html "https://$domain/?smoke=$(date +%s)-$attempt"
    if grep -q "static.cloudflareinsights.com/beacon.min.js" /tmp/smoke-home.html; then echo "Web Analytics beacon present"; break; fi
    [ "$attempt" = 5 ] && { echo "the Web Analytics beacon is missing from https://$domain/"; exit 1; }
    sleep 10
  done
fi
echo "Data generated: $(python3 -c "import json; print(json.load(open('site/data/meta.json'))['generated_at'])")"
