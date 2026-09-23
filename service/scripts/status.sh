#!/usr/bin/env bash
# Read-only check; does not start a service or modify nginx.
set -u
base=${1:-https://www.timeonion.com/mesemondo/api/v1}
failed=0
for endpoint in healthz readyz; do
    printf '%s\n' "${base%/}/$endpoint"
    if ! curl --connect-timeout 3 --max-time 8 --fail --silent --show-error \
        --write-out '\nHTTP %{http_code}, %{time_total} s\n' "${base%/}/$endpoint"; then
        failed=1
    fi
done
if [ "$failed" -ne 0 ]; then
    printf '%s\n' 'Nem elerheto. A 404 hianyzo route/proxyra utal; a script nem inditja el a service-t.' >&2
fi
exit "$failed"
