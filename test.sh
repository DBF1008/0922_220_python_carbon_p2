#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"
export PYTHONPATH="$root_dir/lib${PYTHONPATH:+:$PYTHONPATH}"

python_bin="${PYTHON:-python}"
status=0

while IFS= read -r test_file; do
  module="$(echo "${test_file%.py}" | sed 's#^lib/##; s#/#.#g')"
  echo "==> $module"
  if ! "$python_bin" -m twisted.trial "$module"; then
    status=1
  fi
done < <(find lib/carbon/tests -maxdepth 1 -name 'test_*.py' -type f | sort)

exit "$status"
