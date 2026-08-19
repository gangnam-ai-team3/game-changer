# hy — 수집 담당 파트

담당자: 정현예

Anthropic API(Claude)를 쓰지 않고, 스팀 공식 API + 로컬 계산만으로 끝나는 파이프라인입니다.

## 파일 구성

| 파일 | 역할 | Claude API 사용 |
|---|---|---|
| `steam-db.js` | 스팀 게임 검색 + 로컬 DB(SQLite) 접근 공용 함수 | ❌ |
| `collector.js` | 스팀 공식 리뷰 API에서 전체 리뷰를 언어권별 병렬로 수집해 DB에 적재 | ❌ |
| `prepare-evidence.js` | **hy 담당 파트의 핵심.** 기간 필터 → 너무 짧은 리뷰 삭제 → 근접중복 병합 → 벡터화 | ❌ |
| `call-agent.js` | (선택 사용) `prepare-evidence.js`의 결과 위에 Claude로 사람이 읽는 보고서 문서까지 만듦 | ✅ (여기만) |
| `export-anon-db.js` | 원본 DB를 통째로 복사하면서 steamid만 `author_hash`로 바꾼 **공유용 사본**을 만듦 | ❌ |
| `server.js` | `screen.html` 화면과 위 파일들을 잇는 로컬 서버 | 경로에 따라 다름 |
| `screen.html` | 테스트용 화면 | - |
| `steam-reviews.db` | 수집된 **원본** 리뷰 DB(SQLite, steamid 있음). 절대 공유 금지, git에도 안 올림(`.gitignore`) | - |
| `steam-reviews.anon.db` | `export-anon-db.js`가 만든 **비식별화 사본**(steamid 없음). 공유해도 안전하지만 용량 때문에 git엔 못 올림(Release로만) | - |
| `.hash-salt` | 비식별화 해시에 쓰는 비밀 소금값. **이게 새면 비식별화가 무효화되므로 절대 공유 금지**, git에도 안 올림 | - |

## 파이프라인

```
① 수집 (collector.js, 사람이 수동 실행)
   스팀 공식 appreviews API → 언어권 31개 병렬 → steam-reviews.db

   node collector.js [분]        → 백필(처음부터 끝까지, 이미 끝난 언어는 자동 건너뜀)
   node collector.js sync [분]   → 동기화(DB에 이미 있는 리뷰를 만나면 그 언어는 바로 멈춤 = 새 글만 추가)
                                    나중에 하루 1회 / 1시간 1회로 자동 반복하려면 이 sync 모드를
                                    cron 같은 외부 스케줄러로 주기 실행하면 됨(이 파일 자체는 상시로
                                    계속 도는 프로세스가 아니라 실행할 때마다 한 번 돌고 끝남)

② 기간 필터 (prepare-evidence.js)
   사용자가 지정한 기간(periodStartMs~periodEndMs)에 해당하는 리뷰만 DB에서 조회

③ 너무 짧은 리뷰 삭제 + 근접중복 병합 (prepare-evidence.js)
   - 너무 짧은 리뷰는 통째로 제외 (기준은 아래 "최소 글자수 기준" 참고)
   - 남은 리뷰끼리 문자 3-gram 자카드 유사도 90% 이상이면 하나로 병합(대표 1건 + 중복카운트)

④ 벡터화 (prepare-evidence.js)
   병합 후 남은 리뷰마다 64차원 숫자 벡터 생성(해싱 트릭 — 신경망 아님, 순수 계산)
```

`prepare-evidence.js`의 `prepareEvidence()` 함수 하나를 부르면 ②③④가 한 번에 실행되고,
언어권별 건수 요약 + 최종 벡터화된 근거 배열을 돌려줍니다.

## 최소 글자수 기준 (③에서 "너무 짧다"의 기준)

기준값은 `prepare-evidence.js`의 `CJK_MIN_TEXT_LENGTH` / `DEFAULT_MIN_TEXT_LENGTH` 상수에 있습니다.
숫자를 바꾸면 이 표도 같이 고쳐야 합니다.

| 언어권 | 최소 글자수 | 이유 |
|---|---|---|
| 한국어(koreana), 중국어 간체(schinese), 중국어 번체(tchinese), 일본어(japanese) | **8자** | 음절/한자 하나에 뜻이 압축돼 있어, 짧아도 완결된 문장인 경우가 많음 (실측: "핵쟁이 진짜 많아요" 10자, "外挂太多了真的" 7자, "チーターが多すぎる" 9자 — 전부 완결된 문장) |
| 그 외 언어(영어 등 나머지 27개) | **20자** | 같은 뜻이라도 알파벳 기반 언어는 훨씬 더 많은 글자가 필요 (예: "too many cheaters" 17자) |

이 미만인 리뷰는 최종 결과(`evidence`)에서 아예 빠집니다(중복 비교 대상에서도 제외).

## 중복 병합 기준

두 가지 기준 중 하나라도 걸리면 같은 그룹으로 병합합니다.

- **텍스트 유사도**: 같은 언어권 안에서, 문자 3-gram 자카드 유사도 **90% 이상**(번역돼서 다른 언어로 재게시되는 경우는 범위 밖)
- **작성자+시간창**: 같은 작성자(아래 "비식별화" 참고)가 **30분 이내**에 또 올린 경우 (`AUTHOR_TIME_WINDOW_SECONDS`, `prepare-evidence.js`) — 표현을 완전히 바꿔 다시 써서 텍스트 유사도로는 못 잡는 경우를 보완

그룹 안에서는 텍스트가 가장 긴(정보가 많은) 리뷰를 대표로 남기고, 나머지는 `mergedIds`에 기록, `duplicateCount`로 개수 표시

## 비식별화 — steamid는 결과에 남지 않음

DB에는 원본 steamid가 있지만, `prepareEvidence()`를 거치면 즉시 **단방향 해시**(SHA-256 + 비밀 소금값, 앞 16자)로 치환되어 `authorHash` 필드로만 나갑니다. 같은 사람이 쓴 건지 판단(중복 병합용)은 여전히 가능하지만, 해시값만으로 원래 스팀 계정을 역으로 알아낼 수는 없습니다. 최종 `evidence`에는 원본 `steamid`가 전혀 포함되지 않습니다.

소금값(`hy/.hash-salt`)은 처음 실행할 때 자동으로 무작위 생성되어 로컬에 저장되고, 이후로는 계속 같은 값을 씁니다(그래야 같은 사람이 언제 다시 조회해도 같은 해시가 나옴). steamid는 형식이 정해진 숫자(예: `7656119`로 시작하는 17자리)라서, 소금 없이 그냥 해시만 하면 공격자가 있을 법한 steamid를 미리 다 해시해 둔 표로 역추적할 수 있습니다 — 그래서 소금을 반드시 섞고, 이 파일은 어디에도 공유하지 않습니다.

## 공유할 땐 원본이 아니라 비식별화 사본을 만들어서

원본 DB(`steam-reviews.db`)는 **한 번 밖으로 나가면 되돌릴 수 없으므로** 절대 공유하지 않습니다. 대신:

```
node export-anon-db.js
```

를 실행하면 `steam-reviews.anon.db`(steamid 없이 `author_hash`만 있는 사본)가 만들어집니다. 이 사본은:
- 진짜 SQLite DB라서, `prepareEvidence({ ..., dbPath: './steam-reviews.anon.db' })`처럼 **원본과 똑같은 방식으로 계속 자유롭게 기간·언어를 바꿔가며 조회 가능**합니다(한 번 내보낸 특정 결과 하나로 고정되는 게 아님)
- 실제로 원본과 사본에서 같은 조회를 했을 때 건수·`authorHash` 값이 완전히 동일함을 확인했습니다
- 용량은 원본과 비슷해서(300MB대) 일반 PR(git, 100MB 제한)로는 못 올리고, **GitHub Release 첨부**로만 공유 가능합니다

## 벡터화 방식

신경망 임베딩이 아니라 **해싱 트릭**(scikit-learn의 HashingVectorizer와 같은 원리)입니다.
리뷰 텍스트의 3-gram을 64차원 숫자 벡터로 접어넣고 L2 정규화합니다. 모델 다운로드나 외부 API가 없어
메모리 부담이 거의 없고, 텍스트 밖으로 나가는 정보도 없습니다. 다만 "글자 조합이 얼마나 겹치는지"만
반영하는 통계적 벡터라, 신경망 임베딩만큼 의미(동의어·패러프레이즈)까지 이해하지는 못합니다.

## 서버 API (server.js)

`node server.js` 실행 후 `http://localhost:8787`:

| 경로 | 하는 일 | Claude API |
|---|---|---|
| `GET /` | `screen.html` 반환 | - |
| `POST /evidence` | `prepareEvidence()` 직접 호출 — 핵심 파트 결과(언어권별 요약 + 벡터화된 근거) 반환 | ❌ |
| `POST /call-agent` | (선택) `callAgent()` 호출 — 위 결과 위에 Claude로 사람이 읽는 보고서까지 생성 | ✅ |

`screen.html`의 "[데이터 수집]" 버튼은 `/evidence`만 호출합니다(핵심 파트만 사용, Claude 미사용).

## 알아둘 점 — 키워드 필터링은 이 단계에 없음

이벤트/키워드가 리뷰와 "의미상" 관련 있는지 판단하는 건 이 파트(③④) 범위에 없습니다.
그 정도의 의미 판단은 Claude가 필요해서, 필요하면 `call-agent.js`(Claude 사용)가 그 위에서 처리합니다.
이 README가 다루는 순수 로컬 파트는 기간·중복·길이만 다룹니다.
