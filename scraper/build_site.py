"""GitHub Pages용 지도 사이트 빌드.

data/kahis_outbreaks.csv 의 농장소재지를 법정동(리) 중심 좌표로 변환하고
site/ 의 정적 파일과 함께 _site/ 에 출력한다.

    python scraper/build_site.py [--out _site]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "kahis_outbreaks.csv"
SITE_SRC = ROOT / "site"
CACHE = ROOT / ".cache" / "korea-regions-with-coords.json"

# 법정동 중심 좌표 (출처: 행정안전부 법정동코드, 국토지리정보원 브이월드 경계 / 공공누리 제1유형)
REGIONS_URL = (
    "https://raw.githubusercontent.com/swuhalee/korea-regions-with-coords/"
    "426b795e8f4546eb41a9a46fd35098e9cc515e39/korea-regions-with-coords.json"
)

# 명칭이 바뀐 시도: 원본 표기 -> 현재 법정동 데이터에서 찾을 시도 후보
SIDO_ALIAS = {
    "전라북도": ["전북특별자치도"],
    "강원도": ["강원특별자치도"],
    "전남광주통합특별시": ["전라남도", "광주광역시"],
    "경상북도": ["경상북도", "대구광역시"],  # 군위군 대구 편입
    "충청남도": ["충청남도", "세종특별자치시"],  # 연기군 세종 편입
    "충청북도": ["충청북도", "세종특별자치시"],
}

# 폐지/승격된 시군구
SIGUNGU_ALIAS = {
    "당진군": "당진시",
    "여주군": "여주시",
    "청원군": "청주시",
    "연기군": "",
    "마산시": "창원시",
    "진해시": "창원시",
    "북제주군": "제주시",
    "남제주군": "서귀포시",
}

KST = timezone(timedelta(hours=9))


def load_regions() -> list[dict]:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        resp = requests.get(REGIONS_URL, timeout=120)
        resp.raise_for_status()
        CACHE.write_bytes(resp.content)
    return json.loads(CACHE.read_text(encoding="utf-8"))["sido"]


class Geocoder:
    def __init__(self, regions: list[dict]):
        # 시도를 제외한 주소 -> [(시도, lat, lng)]
        self.by_rest: dict[str, list[tuple[str, float, float]]] = defaultdict(list)
        # 마지막 2개 토큰(읍면동 리) -> [(시도, lat, lng)]
        self.by_tail: dict[str, list[tuple[str, float, float]]] = defaultdict(list)

        def walk(node: dict, path: list[str]) -> None:
            p = path + [node["name"]]
            if "lat" in node and len(p) > 1:
                hit = (p[0], node["lat"], node["lng"])
                self.by_rest[" ".join(p[1:])].append(hit)
                if len(p) >= 3:
                    self.by_tail[" ".join(p[-2:])].append(hit)
            for child in node.get("children", []):
                walk(child, p)

        for sido in regions:
            walk(sido, [])

    @staticmethod
    def _pick(hits, sidos):
        same = [h for h in hits if h[0] in sidos]
        if len(same) == 1 or (same and len({(h[1], h[2]) for h in same}) == 1):
            return same[0]
        return None

    def geocode(self, address: str) -> tuple[float, float, int] | None:
        """(lat, lng, 정밀도) 반환. 정밀도 2=주소 전체 일치, 1=상위 행정구역 좌표로 대체."""
        tokens = address.split()
        if len(tokens) < 2:
            return None
        sido, rest = tokens[0], tokens[1:]
        sidos = [sido] + SIDO_ALIAS.get(sido, [])
        rest = [SIGUNGU_ALIAS.get(t, t) for t in rest]
        rest = [t for t in rest if t]

        for n in range(len(rest), 0, -1):
            hit = self._pick(self.by_rest.get(" ".join(rest[:n]), []), sidos)
            if hit:
                return hit[1], hit[2], 2 if n == len(rest) else 1
            # 시군구가 바뀐 경우: 읍면동+리 조합으로 시도 내 검색
            if n >= 3:
                hit = self._pick(self.by_tail.get(" ".join(rest[n - 2 : n]), []), sidos)
                if hit:
                    return hit[1], hit[2], 2 if n == len(rest) else 1
        return None


def build(out: Path) -> None:
    df = pd.read_csv(CSV, dtype=str, keep_default_na=False, encoding="utf-8")
    geocoder = Geocoder(load_regions())

    coords = {a: geocoder.geocode(a) for a in df["농장소재지"].unique()}
    missing = df["농장소재지"].map(lambda a: coords[a] is None)
    print(f"[info] 좌표 변환: {len(df) - missing.sum()}/{len(df)}건 성공")

    diseases = sorted(df["가축전염병명"].unique())
    species = sorted(df["축종"].unique())
    d_idx = {v: i for i, v in enumerate(diseases)}
    s_idx = {v: i for i, v in enumerate(species)}

    rows = []
    for r in df.itertuples(index=False):
        c = coords[r.농장소재지]
        heads = int(r.발생두수) if r.발생두수.isdigit() else None
        rows.append(
            [
                r.진단일,
                r.발생일자,
                d_idx[r.가축전염병명],
                s_idx[r.축종],
                r.품종,
                r.농장명,
                r.농장소재지,
                heads,
                r.진단기관,
                r.종식일,
                round(c[0], 5) if c else None,
                round(c[1], 5) if c else None,
                c[2] if c else 0,
            ]
        )

    payload = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "fields": [
            "진단일", "발생일자", "가축전염병명", "축종", "품종", "농장명",
            "농장소재지", "발생두수", "진단기관", "종식일", "lat", "lng", "precision",
        ],
        "diseases": diseases,
        "species": species,
        "rows": rows,
    }

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out)
    (out / "data").mkdir(exist_ok=True)
    (out / "data" / "outbreaks.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    shutil.copy(CSV, out / "data" / CSV.name)
    print(f"[done] {out} 생성")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    args = parser.parse_args(argv)
    build(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
