# -*- coding: utf-8 -*-
"""
Fortnite パワーランキング取得スクリプト

Fortnite 公式サイトの power-rankings データAPIから
  ・PR順位 (rank)
  ・プレイヤー名 (displayName)
  ・PRレーティング (score)
を取得して JSON ファイルに保存する。

このAPIは React Router(Remix) の turbo-stream 形式
（インデックス参照で値を相互参照するフラット配列）を返すため、
デコード処理を行う。

使い方:
    python fetch_power_rankings.py                       # ASIA / 100件
    python fetch_power_rankings.py --region EU           # 地域を変更
    python fetch_power_rankings.py --page-size 50        # 件数を変更
    python fetch_power_rankings.py -o out.json           # 出力先を指定
"""

import argparse
import json
import subprocess
import sys
import urllib.parse

# Windows コンソールでの日本語出力対策
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API_URL = "https://www.fortnite.com/competitive/power-rankings.data"


def fetch_raw(region, page_size):
    """API を叩いて turbo-stream のフラット配列(list)を返す。

    Cloudflare が Python(urllib/requests) の通信を bot として弾くため、
    OS 標準の curl を経由して取得する（Windows 10/11・macOS・Linux 標準搭載）。
    """
    query = urllib.parse.urlencode({"region": region, "pageSize": page_size})
    url = f"{API_URL}?{query}"
    headers = [
        # Cloudflare を通過させるためブラウザを装う
        "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept: */*",
        "Accept-Language: en-US,en;q=0.9",
        f"Referer: https://www.fortnite.com/competitive/power-rankings?region={region}",
    ]
    cmd = ["curl", "-s", "--fail", "--compressed", url]
    for h in headers:
        cmd += ["-H", h]

    try:
        proc = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError:
        raise RuntimeError("curl が見つかりません。curl をインストールしてください。")
    if proc.returncode != 0:
        raise RuntimeError(
            f"取得に失敗しました (curl 終了コード {proc.returncode})。"
            "Cloudflare にブロックされた可能性があります。"
        )

    body = proc.stdout.decode("utf-8")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # JSON でない場合は Cloudflare のチャレンジ画面などが返っている
        raise RuntimeError(
            "JSON を取得できませんでした。Cloudflare にブロックされた可能性があります。"
        )


class TurboStreamDecoder:
    """turbo-stream のフラット配列をデコードする。

    - 各スロット flat[i] には 文字列 / 数値 / 真偽値 / dict / list が入る。
    - dict は {"_<キー文字列のスロット番号>": 値のスロット番号} の形。
    - list の各要素も「値のスロット番号」。
    - 負数のスロット番号は undefined / null などの特殊値 → None として扱う。
    """

    def __init__(self, flat):
        self.flat = flat
        self.memo = {}

    def _resolve(self, ref):
        """dict の値や list の要素（スロット番号）を実体に変換する。"""
        if not isinstance(ref, int):
            return ref
        if ref < 0:               # undefined / null などの特殊値
            return None
        return self._slot(ref)

    def _slot(self, i):
        """flat[i] のスロットを実体に変換する（メモ化で循環参照に対応）。"""
        if i in self.memo:
            return self.memo[i]
        raw = self.flat[i]
        if isinstance(raw, dict):
            obj = {}
            self.memo[i] = obj
            for k, v in raw.items():
                key = self._slot(int(k[1:]))   # "_123" -> flat[123]（=キー文字列）
                obj[key] = self._resolve(v)
            return obj
        if isinstance(raw, list):
            arr = []
            self.memo[i] = arr
            for e in raw:
                arr.append(self._resolve(e))
            return arr
        self.memo[i] = raw
        return raw

    def decode(self):
        return self._slot(0)


def deep_find(obj, key):
    """デコード済みの入れ子構造から、最初に見つかった key の値を返す。"""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = deep_find(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = deep_find(v, key)
            if found is not None:
                return found
    return None


def main():
    parser = argparse.ArgumentParser(description="Fortnite パワーランキング取得")
    parser.add_argument("--region", default="ASIA",
                        help="地域 (ASIA / NAC / NAW / EU / BR / ME / OCE 等). 既定: ASIA")
    parser.add_argument("--page-size", type=int, default=100,
                        help="取得件数. 既定: 100")
    parser.add_argument("-o", "--output", default=None,
                        help="出力ファイル名. 既定: power-rankings_<region>.json")
    args = parser.parse_args()

    output = args.output or f"power-rankings_{args.region}.json"

    print(f"取得中: region={args.region}, pageSize={args.page_size} ...")
    flat = fetch_raw(args.region, args.page_size)

    decoded = TurboStreamDecoder(flat).decode()
    rows = deep_find(decoded, "leaderboardRows") or []

    rankings = [
        {
            "rank": row.get("rank"),                # PR順位
            "displayName": row.get("displayName"),  # プレイヤー名
            "score": row.get("score"),              # PRレーティング
        }
        for row in rows
        if isinstance(row, dict)
    ]
    # 順位順に並べ替え（rank が無いものは末尾へ）
    rankings.sort(key=lambda r: (r["rank"] is None, r["rank"] or 0))

    with open(output, "w", encoding="utf-8") as f:
        json.dump(rankings, f, ensure_ascii=False, indent=2)

    print(f"完了: {len(rankings)} 件を {output} に保存しました。")
    for r in rankings[:5]:
        print(f"  #{r['rank']:<3} {r['displayName']}  (PR: {r['score']})")


if __name__ == "__main__":
    main()
