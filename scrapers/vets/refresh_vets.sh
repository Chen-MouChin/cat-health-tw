#!/usr/bin/env bash
# 獸醫院資料一鍵更新
#
# 用法：
#   ./scrapers/vets/refresh_vets.sh           # 全部三層
#   ./scrapers/vets/refresh_vets.sh layer1    # 只跑 Layer 1
#   ./scrapers/vets/refresh_vets.sh layer2    # 只跑 Layer 2
#   ./scrapers/vets/refresh_vets.sh layer3    # 只跑 Layer 3

set -e
cd "$(dirname "$0")/../.."

TARGET=${1:-all}

if [[ "$TARGET" == "all" || "$TARGET" == "layer1" ]]; then
  echo "=== Layer 1: 政府 open data ==="
  python3 scrapers/vets/layer1_opendata.py --all
fi

if [[ "$TARGET" == "all" || "$TARGET" == "layer2" ]]; then
  echo ""
  echo "=== Layer 2: Google Maps ==="
  python3 scrapers/vets/layer2_gmaps.py
fi

if [[ "$TARGET" == "all" || "$TARGET" == "layer3" ]]; then
  echo ""
  echo "=== Layer 3: Website/Blog ==="
  python3 scrapers/vets/layer3_website.py --city 台北市 --limit 50
  python3 scrapers/vets/layer3_website.py --city 新北市 --limit 50
  python3 scrapers/vets/layer3_website.py --city 高雄市 --limit 50
fi

echo ""
echo "=== Done ==="
