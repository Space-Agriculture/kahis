# kahis

[국가가축방역통합시스템(KAHIS)](https://home.kahis.go.kr/home/lkntscrinfo/selectLkntsOccrrncList.do)의
**법정가축전염병 발생현황**을 매일 수집해 CSV 파일로 정리하는 저장소입니다.

- 수집 주기: GitHub Actions로 **매일 18:00(KST)** 실행 (`.github/workflows/crawl.yml`)
- 결과 파일: [`data/kahis_outbreaks.csv`](data/kahis_outbreaks.csv) (UTF-8, 누적 단일 파일)
- 수집 범위: 2000-01-01 이후 전체 이력. 매일 **최근 365일(진단일 기준)** 을 다시 수집해 기존 데이터의 해당 기간을 교체합니다.
  이렇게 하면 늦게 등록되거나 수정된 건, 종식일 갱신도 반영됩니다.
- 정렬: 진단일 내림차순

> GitHub Actions 스케줄은 서버 상황에 따라 수 분~수십 분 늦게 실행될 수 있습니다.

## CSV 컬럼

| 컬럼 | 설명 | 예시 |
|---|---|---|
| 가축전염병명 | 법정가축전염병명 | 럼피스킨병 |
| 농장명 | 농장명(농장주). 비공개(`.`)는 빈 값 | 허인석농장 |
| 농장소재지 | 농장 소재지(시도 시군구 읍면동 리) | 전북특별자치도 부안군 보안면 월천리 |
| 발생일자 | 발생일 (`YYYY-MM-DD`) | 2026-11-02 |
| 진단일 | 진단일 (`YYYY-MM-DD`) | 2026-11-03 |
| 축종 | 축종 | 소 |
| 품종 | 품종 | 한우 |
| 발생두수 | 발생두수(마리) | 1 |
| 진단기관 | 진단기관 | 동물위생시험소 |
| 종식일 | 종식일(없으면 빈 값) | |

원본 값은 그대로 보존합니다. 원본에 입력 오류(예: 발생일자 `4026-10-04`)가 있으면 날짜 변환 때 `NA`가 될 수 있습니다.
발생두수가 미상인 경우 원본에는 `-`로 표기되어 있으며, 아래 함수들은 이를 `NA`로 변환합니다.

## 데이터 불러오기

CSV 주소:

```
https://raw.githubusercontent.com/Space-Agriculture/kahis/main/data/kahis_outbreaks.csv
```

### Python (pandas)

```python
import pandas as pd

KAHIS_URL = "https://raw.githubusercontent.com/Space-Agriculture/kahis/main/data/kahis_outbreaks.csv"


def load_kahis(path: str = KAHIS_URL, parse_dates: bool = True) -> pd.DataFrame:
    """KAHIS 가축전염병 발생현황 CSV를 DataFrame으로 불러온다."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    df["발생두수"] = pd.to_numeric(df["발생두수"], errors="coerce").astype("Int64")
    if parse_dates:
        for col in ["발생일자", "진단일", "종식일"]:
            df[col] = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")
    return df


df = load_kahis()
# 예) 2026년 진단된 질병별 발생 건수
print(df[df["진단일"].dt.year == 2026]["가축전염병명"].value_counts())
```

### R (readr / tidyverse)

```r
library(readr)

KAHIS_URL <- "https://raw.githubusercontent.com/Space-Agriculture/kahis/main/data/kahis_outbreaks.csv"

load_kahis <- function(path = KAHIS_URL) {
  read_csv(
    path,
    locale = locale(encoding = "UTF-8"),
    na = c("", "NA", "-"),
    col_types = cols(
      .default = col_character(),
      발생일자 = col_date("%Y-%m-%d"),
      진단일 = col_date("%Y-%m-%d"),
      종식일 = col_date("%Y-%m-%d"),
      발생두수 = col_integer()
    )
  )
}

df <- load_kahis()
# 예) 질병별 발생 건수
dplyr::count(df, 가축전염병명, sort = TRUE)
```

### R (base R, 추가 패키지 없이 사용)

```r
KAHIS_URL <- "https://raw.githubusercontent.com/Space-Agriculture/kahis/main/data/kahis_outbreaks.csv"

load_kahis_base <- function(path = KAHIS_URL) {
  df <- read.csv(path, fileEncoding = "UTF-8", encoding = "UTF-8",
                 colClasses = "character", na.strings = c("", "-"), check.names = FALSE)
  for (col in c("발생일자", "진단일", "종식일")) {
    df[[col]] <- as.Date(df[[col]], format = "%Y-%m-%d")
  }
  df[["발생두수"]] <- suppressWarnings(as.integer(df[["발생두수"]]))
  df
}

df <- load_kahis_base()
str(df)
```

> 날짜 형식이 맞지 않는 값(원본 입력 오류)은 R에서는 `NA`, Python에서는 `NaT`로 변환됩니다.

## 직접 실행하기

```bash
pip install -r requirements.txt
python scraper/kahis.py              # CSV가 없으면 전체 수집, 있으면 최근 365일 갱신
python scraper/kahis.py --days 30    # 최근 30일만 갱신
python scraper/kahis.py --full       # 전체 이력 재수집
```

GitHub의 **Actions → KAHIS daily crawl → Run workflow** 에서 수동으로도 실행할 수 있습니다(`full`, `days` 옵션 지원).

## 구성

```
scraper/kahis.py               # 크롤러 (requests + BeautifulSoup)
.github/workflows/crawl.yml    # 매일 18:00 KST 실행, 변경 시 자동 커밋
data/kahis_outbreaks.csv       # 수집 결과
requirements.txt
```

## 출처

- 데이터 출처: 농림축산식품부 국가가축방역통합시스템(KAHIS)
- 데이터의 정확성과 최신성은 원 출처를 기준으로 하며, 이 저장소는 공개된 정보를 정리한 것입니다.
