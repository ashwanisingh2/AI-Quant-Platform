#!/bin/sh
# Dev API server — CI-matching API_AUTH_TOKEN ke saath.
# Token literal kahin type nahi hota — .github/workflows/ci.yml se runtime parse.
cd "$(dirname "$0")/.." || exit 1
TOK=$(grep -oE 'API_AUTH_TOKEN: [^ ]+' .github/workflows/ci.yml | head -1 | cut -d' ' -f2)
if [ "${#TOK}" -lt 32 ]; then
    echo "❌ Token parse fail (len ${#TOK}) — ci.yml mein API_AUTH_TOKEN check karo"
    exit 1
fi
echo "✅ API_AUTH_TOKEN loaded from ci.yml (len ${#TOK})"
exec env API_AUTH_TOKEN="$TOK" python3 -m apps.api.main
