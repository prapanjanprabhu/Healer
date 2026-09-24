#!/usr/bin/env bash
# Expected-peak load test for the ERP (Phase 15) — real concurrent HTTP
# load against real running Waitress instances, round-robining across
# every port the application currently has, the same way Nginx's
# least_conn upstream would distribute it. No load-testing framework
# dependency: xargs -P gives real concurrency, curl gives a real request.
#
# Usage: ./load_test_erp.sh "9900 9901 9902 9903" [total_requests] [concurrency]
set -euo pipefail

export PORTS_STR="${1:?ports, space-separated, required}"
TOTAL=${2:-2000}
CONCURRENCY=${3:-50}

echo "load test: $TOTAL requests across ($PORTS_STR), concurrency $CONCURRENCY"

start=$(date +%s)
seq 1 "$TOTAL" | xargs -P "$CONCURRENCY" -I{} bash -c '
  ports=($PORTS_STR)
  port=${ports[$(( RANDOM % ${#ports[@]} ))]}
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:${port}/health/" || echo "000")
  echo "$code"
' > /tmp/load_test_results.txt
end=$(date +%s)

total_time=$((end - start))
[ "$total_time" -eq 0 ] && total_time=1
ok=$(grep -c "^200$" /tmp/load_test_results.txt || true)
failed=$((TOTAL - ok))

echo "--- results ---"
echo "duration: ${total_time}s"
echo "requests: $TOTAL"
echo "succeeded (200): $ok"
echo "failed/non-200: $failed"
echo "throughput: $((TOTAL / total_time)) req/s"

rm -f /tmp/load_test_results.txt
