#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$root_dir"

export GRAPHITE_NO_PREFIX=true
export PYTHONPATH="$root_dir/lib${PYTHONPATH:+:$PYTHONPATH}"
python_bin="${PYTHON:-python}"

if "$python_bin" -c 'import twisted.trial' >/dev/null 2>&1; then
  trial_runner=("$python_bin" -m twisted.trial)
elif command -v trial >/dev/null 2>&1; then
  trial_runner=(trial)
else
  echo "Twisted trial is not available. Install requirements first." >&2
  exit 1
fi

find lib/carbon/tests -maxdepth 1 -name 'test_*.py' -print | sort | while IFS= read -r test_file; do
  test_module="$(basename "$test_file" .py)"
  echo "Running carbon.tests.$test_module"
  "${trial_runner[@]}" "carbon.tests.$test_module"
done
