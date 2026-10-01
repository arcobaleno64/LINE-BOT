#!/bin/bash
# scripts/verify-deployment.sh
# 部署後驗證：確認服務健康、執行版本與 Webhook 簽名閘道
set -euo pipefail

TARGET="${1:-}"
EXPECTED_COMMIT="${2:-}"
if [ -z "$TARGET" ] || [ -z "$EXPECTED_COMMIT" ]; then
    echo "Usage: $0 <host-or-url> <expected-commit-sha>"
    exit 1
fi
if [[ ! "$EXPECTED_COMMIT" =~ ^[[:xdigit:]]{40}$ ]]; then
    echo "Expected commit must be a full 40-character Git SHA"
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

        DEPLOYED_COMMIT=$(curl -fsS --max-time 5 "$BASE_URL/version" 2>/dev/null || true)
        if [ "$DEPLOYED_COMMIT" != "$EXPECTED_COMMIT" ]; then
            if [ "$i" -lt "$MAX" ]; then
                echo "  Attempt $i/$MAX: /version returned ${DEPLOYED_COMMIT:-no commit}; expected $EXPECTED_COMMIT, retrying in ${INTERVAL}s..."
                sleep "$INTERVAL"
            else
                echo "  Attempt $i/$MAX: /version still does not match expected commit $EXPECTED_COMMIT"
            fi
            continue
        fi
        echo "✓ /version returned expected commit $EXPECTED_COMMIT"

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

echo "✗ Deployment did not report expected commit $EXPECTED_COMMIT after $MAX attempts"
exit 1
