#!/bin/sh
# Supply a private token in the environment; never reuse CI credentials.
set -eu
cd "$(dirname "$0")/.." || exit 1
API_AUTH_TOKEN=${API_AUTH_TOKEN:-}
export API_AUTH_TOKEN
if [ "${#API_AUTH_TOKEN}" -lt 32 ]; then
    echo "Set API_AUTH_TOKEN to a private random token of at least 32 characters." >&2
    exit 1
fi
case "$API_AUTH_TOKEN" in
    ci-only-*) echo "CI tokens are not allowed for a development server." >&2; exit 1 ;;
esac
exec python3 -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
