"""KAHIS 법정가축전염병 발생현황 크롤러.

https://home.kahis.go.kr/home/lkntscrinfo/selectLkntsOccrrncList.do 의 목록을
수집하여 data/kahis_outbreaks.csv 에 누적 저장한다.

사용법:
    python scraper/kahis.py            # CSV가 없으면 전체 수집, 있으면 최근 N일 갱신
    python scraper/kahis.py --full     # 전체 이력 재수집
    python scraper/kahis.py --days 30  # 최근 30일(진단일 기준) 갱신
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

URL = "https://home.kahis.go.kr/home/lkntscrinfo/selectLkntsOccrrncList.do"
START_DATE = "2000-01-01"
PAGE_UNIT = 1000
DEFAULT_DAYS = 365
KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "kahis_outbreaks.csv"

COLUMNS = [
    "가축전염병명",
    "농장명",
    "농장소재지",
    "발생일자",
    "진단일",
    "축종",
    "품종",
    "발생두수",
    "진단기관",
    "종식일",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; kahis-crawler/1.0; "
        "+https://github.com/Space-Agriculture/kahis)"
    ),
    "Referer": URL,
}

TOTAL_RE = re.compile(r"전체\s*:\s*([\d,]+)\s*건")
DATES_RE = re.compile(r"^\s*([^()]*?)\s*(?:\(\s*([^()]*?)\s*\))?\s*$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def fetch_page(session: requests.Session, page: int, from_dt: str, to_dt: str) -> str:
    data = {
        "pageIndex": page,
        "pageUnit": PAGE_UNIT,
        "turmGubun": "01",  # 01=진단일 기준, 02=발생일 기준
        "occrFromDt": from_dt,
        "occrToDt": to_dt,
    }
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            resp = session.post(URL, data=data, headers=HEADERS, timeout=120)
            resp.raise_for_status()
            resp.encoding = resp.encoding or "utf-8"
            if "list_g_line" not in resp.text and not TOTAL_RE.search(resp.text):
                raise RuntimeError("예상한 목록 테이블이 응답에 없습니다.")
            return resp.text
        except Exception as err:  # noqa: BLE001
            last_err = err
            wait = 5 * 2**attempt
            print(f"[warn] page {page} 요청 실패({err}); {wait}s 후 재시도", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"page {page} 수집 실패: {last_err}")


def parse_total(html: str) -> int:
    m = TOTAL_RE.search(html)
    if not m:
        raise RuntimeError("전체 건수를 찾을 수 없습니다.")
    return int(m.group(1).replace(",", ""))


def parse_rows(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) != 8 or not all(
            any(c.startswith("list_g_line") for c in (td.get("class") or [])) for td in tds
        ):
            continue
        cells = [_clean(td.get_text(" ")) for td in tds]
        disease, farm, addr, dates, species, count, lab, end_dt = cells

        m = DATES_RE.match(dates)
        occur_dt, diag_dt = (m.group(1), m.group(2) or "") if m else (dates, "")
        animal, _, breed = species.partition("-")

        rows.append(
            {
                "가축전염병명": disease,
                "농장명": "" if farm == "." else farm,
                "농장소재지": addr,
                "발생일자": occur_dt,
                "진단일": diag_dt,
                "축종": animal.strip(),
                "품종": breed.strip(),
                "발생두수": count.replace(",", ""),
                "진단기관": lab,
                "종식일": end_dt,
            }
        )
    return rows


def crawl(from_dt: str, to_dt: str, delay: float = 1.0) -> pd.DataFrame:
    session = requests.Session()
    first = fetch_page(session, 1, from_dt, to_dt)
    total = parse_total(first)
    pages = max(1, math.ceil(total / PAGE_UNIT))
    print(f"[info] {from_dt} ~ {to_dt}: 전체 {total}건, {pages}페이지")

    rows = parse_rows(first)
    for page in range(2, pages + 1):
        time.sleep(delay)
        rows.extend(parse_rows(fetch_page(session, page, from_dt, to_dt)))
        print(f"[info] page {page}/{pages} 누적 {len(rows)}건")

    if len(rows) != total:
        raise RuntimeError(f"수집 건수 불일치: 기대 {total}건, 파싱 {len(rows)}건")
    return pd.DataFrame(rows, columns=COLUMNS).astype(str)


def finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.fillna("").astype(str)
    keys = ["진단일", "발생일자"] + [c for c in COLUMNS if c not in ("진단일", "발생일자")]
    return df.sort_values(
        keys, ascending=[False, False] + [True] * (len(keys) - 2), kind="stable"
    ).reset_index(drop=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KAHIS 가축전염병 발생현황 크롤러")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--full", action="store_true", help="전체 이력 재수집")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="증분 수집 기간(일)")
    parser.add_argument("--delay", type=float, default=1.0, help="페이지 간 대기(초)")
    args = parser.parse_args(argv)

    today = datetime.now(KST).date()
    to_dt = today.isoformat()
    output: Path = args.output
    existing = (
        pd.read_csv(output, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        if output.exists()
        else None
    )

    if args.full or existing is None or existing.empty:
        new = crawl(START_DATE, to_dt, args.delay)
        if new.empty:
            raise RuntimeError("수집된 데이터가 없습니다. 기존 파일을 유지합니다.")
        result = new
    else:
        from_dt = (today - timedelta(days=args.days)).isoformat()
        new = crawl(from_dt, to_dt, args.delay)
        # 조회 기간(진단일 기준)에 해당하는 기존 행은 최신 수집분으로 교체
        in_window = (existing["진단일"] >= from_dt) & (existing["진단일"] <= to_dt)
        if new.empty and in_window.sum() > 0:
            raise RuntimeError("최근 기간 수집 결과가 0건입니다. 기존 파일을 유지합니다.")
        result = pd.concat([existing[~in_window], new], ignore_index=True)

    result = finalize(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8")
    print(f"[done] {output} 저장: {len(result)}건 (기준일 {to_dt})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
