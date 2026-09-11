# 문의함 (Munuiham)

카카오·모바일 웹용 문의 접수 / 관리 MVP. 템플릿:

1. **분양(아파트)** — `dalseo-prugio`
2. **인테리어 견적** — `interior-quote`

## 빠른 시작

```bash
cd /workspace/munuiham
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ADMIN_PASSWORD=change-me
export SESSION_SECRET=any-random-string
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

또는:

```bash
./run.sh
```

### URL

| 용도 | 경로 |
|------|------|
| 분양 랜딩 (`/` 동일) | `/` , `/l/dalseo-prugio` |
| 분양 문의 폼 | `/f/dalseo-prugio` |
| 인테리어 견적 폼 | `/f/interior-quote` |
| 관리자 | `/admin` |

- 기본 관리자 비밀번호: **`change-me`** (`ADMIN_PASSWORD` 환경변수로 변경)
- `/` 는 분양 랜딩 유지. 인테리어는 `/f/interior-quote` 전용.

## 데이터

SQLite 파일: `data/munuiham.db` (프로젝트 폴더에 파일로 저장)

## 기능

- 모바일 한국어 공개 폼 2종 + 분양 랜딩
- 허니팟 + IP 기준 간단 rate limit (10분에 5회)
- 관리자 비밀번호 로그인, 문의 목록/미읽음, 상태·메모
- 인테리어 리드: 관리자에서 방문예정 → **실측예정** 라벨 표시 (DB 값은 동일). 견적발송은 메모에 기록.
- 시드 폼: `dalseo-prugio`, `interior-quote` (INSERT OR IGNORE)

## 필드 매핑 (인테리어 → leads)

| 고객 필드 | leads 컬럼 |
|-----------|------------|
| 이름 / 연락처 | `name` / `phone` |
| 시공 지역 | `complex_name` (비우면 샵 기본값 `한빛인테리어`) |
| 예산대 | `budget` |
| 평수 | `unit_size` |
| 희망 시기 | `move_timing` |
| 시공 유형 | `meta` JSON `{"work_type": "..."}` + 문의 내용 앞에 `[시공유형]` prefix |
| 문의 내용 | `message` |
| 유입경로 | `source` |

분양 폼은 기존과 동일: `unit_size`=타입, `move_timing`=연령대(age_group), `complex_name`=관심 단지.

## 폰 테스트용 공개 URL

서버를 `0.0.0.0`에 바인딩한 뒤 cloudflared / localtunnel 등으로 HTTPS 터널을 열면 됩니다.
터널 URL은 실행 시 `URLS.txt`에 기록합니다.

```bash
./bin/start_tunnel.sh
```

## 현재 폰 테스트 URL (2026-09-07)

- 분양 랜딩: https://holdem-lookup-overseas-rotary.trycloudflare.com/
- 분양 폼: https://holdem-lookup-overseas-rotary.trycloudflare.com/f/dalseo-prugio
- 인테리어 폼: https://holdem-lookup-overseas-rotary.trycloudflare.com/f/interior-quote
- 관리자: https://holdem-lookup-overseas-rotary.trycloudflare.com/admin
- 비밀번호: `change-me`
- 상세: `URLS.txt`
