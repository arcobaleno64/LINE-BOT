#!/bin/bash
# scripts/verify-deployment.sh
# 部署後存活驗證：確認服務健康 + Webhook 簽名閘道正常
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
    echo "Usage: $0 <host-or-url>"
  exit 1
fi

case "$TARGET" in
    http://*|https://*)
        BASE_URL="${TARGET%/}"
        ;;
    *)
        BASE_URL="https://${TARGET%/}"
        ;;
esac

MAX=12
INTERVAL=10

echo "Verifying deployment at $BASE_URL ..."

for i in $(seq 1 $MAX); do
        HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BASE_URL/health" 2>/dev/null || echo "000")
    if [ "$HTTP" = "200" ]; then
        echo "✓ /health returned 200 after $((i * INTERVAL))s"

        # 確認 Webhook 簽名閘道正常拒絕無效請求
        REJECT=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
                        -X POST "$BASE_URL/api/line/webhook" \
            -H "x-line-signature: invalid-signature" \
            -H "Content-Type: application/json" \
            -d '{"events":[]}' 2>/dev/null || echo "000")

        if [ "$REJECT" = "401" ]; then
            echo "✓ Webhook signature gate returned 401 as expected"
            echo "Deployment verified."
            exit 0
        else
            echo "✗ Webhook signature gate returned $REJECT (expected 401)"
            echo "Signature verification may be broken — aborting."
            exit 2
        fi
    fi

    echo "  Attempt $i/$MAX: /health returned HTTP $HTTP, retrying in ${INTERVAL}s..."
    sleep $INTERVAL
done

echo "✗ Service did not become healthy after $((MAX * INTERVAL))s"
exit 1
