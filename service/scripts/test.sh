#!/usr/bin/env bash
set -euo pipefail
: "${MM02_CONFIG:?Set MM02_CONFIG to an external dev config}"
: "${MM02_TEST_TMP:?Set MM02_TEST_TMP to a disposable path outside the repository}"
MM02_PYTHON=${MM02_PYTHON:-/opt/mesemondo-tools/venv/bin/python}
MM02_REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
case "$(realpath -m -- "$MM02_TEST_TMP")/" in
  "$MM02_REPO/"*) echo 'Test outputs must be outside the repository' >&2; exit 1;;
esac
export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$MM02_REPO/service"
exec "$MM02_PYTHON" -m pytest "$MM02_REPO/service/tests" -q -p no:cacheprovider --basetemp="$MM02_TEST_TMP" "$@"
