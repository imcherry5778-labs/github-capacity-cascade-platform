# P9 — same-Pod lifetime ring capacity 교정

[Blocking review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5756349012)에 대한 cost-free 교정이다.
Exact source commit `d4beffff56c6a3966b5f26531976893db7cfe31b`에서 검증했다. 기존4MiB proof는 별도 source의 관측으로 보존한다.
**Azure/Secret/credential API·publish·paid workload는 수행하지 않았다. Campaign24 권한과 P9 acceptance는 없다.**

## Capacity 계산과 source gate

Ring은 run별로 비워지는 저장소가 아니다. C0/C1은 같은 HAProxy UID/config를 유지한다.
Current420초 plan의4116은 client attempt 상한이며 Git 내부 HTTP와 동일한 check 수가 아니다.
Capacity에는 `ls-remote`의 discovery와 v2 `ls-refs`를2 HTTP로 예약해 run당4200 row를 사용한다.
Source의 더 큰 허용 plan300+240초로 모든6회를 보수적으로 계산했다. 실제 plan/wave/SLO/approval limit는 변경하지 않았다.

| 항목 | Lifetime reserve |
| --- | ---: |
| 최대540초 / 5초 | 108 waves/run |
| Issue24 × max attempts2 | 5184 HTTP/run |
| Git1 command × discovery/ls-refs2 | 216 HTTP/run |
| Calibration2 + measured4, reset 가정 없음 | 6 × 5400 = 32400 |
| 초기/최종 normal + healthy, 각1회 | 3 × 87 = 261 |
| native-deny / controlled-deny / path, 각각2 HTTP reserve | 6 |
| 총합 | **32667 row** |

Journey87은 fixed HTTP11(anonymous Git discovery 포함) + Git HTTP16(push3×2, ls-remote2×2, clone/fetch2×3) + settle poll60이다.
이는 selected healthy smart-HTTP 경로의 용량 예약이며 actual check 수를 추정·합성하는 accounting이 아니다.
[Git HTTP](https://git-scm.com/docs/gitprotocol-http)와 [protocol v2](https://git-scm.com/docs/gitprotocol-v2)의 discovery/command 분리를 반영했다.
실제 check 수는 여전히 log·native counters·ingress/target 보존식으로 검증한다.
Direct sentinel은 source `request(direct=True)`의127.0.0.1:13000으로 ingress/HAProxy를 우회한다.
최대 약3600 sentinel, loopback readiness·CLI/AMW 수집은 check frontend row0이다. CUSTOM을 먼저 제거하는 owned cleanup도 ring을 사용하지 않는다.

`(32667+1)×512 = 16726016 bytes`로, 기존4MiB는 부족하고16MiB(16777216 bytes)가 이를 담는 최소 power-of-two 크기다.
512-byte slot에는 기존 parser의 line/metadata 여유가 포함되며51200 bytes를 더 남긴다.
Pure source/approval preflight는 최대 campaign 전체가 들어가는지 credential/cloud 호출 전에 확인한다.
매 run 전에는 **실제 lifetime prefix + 현재를 포함한 남은 모든 run의5400씩 + final journey/probe reserve**를 확인하고
preflight record를 남긴다. Prefix가 예상보다 크면 부하 전에 fail closed한다. Reset/overwrite/불완전 수집 guard는 유지한다.

## Pinned Docker 실제 결과

기존 HAProxy3.4.6-alpine digest, Linux amd64, CPU250m/memory256Mi cap이다.
C0/C1 config가 같음을 확인하고 **한 container/config/process**에 initial reserve174 → 5400씩6회 → tail reserve93을 연속 발행했다.
각 경계에서 capacity preflight와 실제 drained frontend counter/row equality를 확인했고 중간에는 concurrent load 중 dump도 수집했다.

- **32667 responses = ring rows = frontend stot**, 동일 UID/PID/start-time lifetime1개, restart0, ring dropped0.
- C0 최대 capture **0.591초 <15초**. 실제 cgroup memory peak **143233024 bytes(136.60MiB) <256MiB**.
  `memory.current/peak/max/events` 원본에 `oom=0`, `oom_kill=0`, OOMKilled=false를 확인했다. Ring 단독 RSS로 해석하지 않는다.
- 별도 C1/C2/C3 generated render도 실제 검증했다. Stdout DroppedLogs는 diagnostic으로 보존하며 C2의 PR/sQ/transport error를 제거하지 않았다.
  기존 tiny-ring overwrite와 실제400/CR/Tw=-1 negative도 fail closed였다.
- Docker opt-in2 tests 실제 PASS(169.845초), P9 138 tests PASS(known skip3), P8 38 tests PASS.
  이 시험은 accelerated HTTP capture stress이며 실제6개 P9 run·Git protocol/native auth·recovery SLO의 성공이 아니다.

Source/test hash, raw9개 size/SHA256·roundtrip·publication scan을 확인했다.
[Execution](execution.json), [raw index](raw-index.json), [원본 local raw](raw-evidence.tar.gz)를 함께 본다.
최종 exact-head CI와 skip 여부는 PR #49 결과 comment에 기록한다.

**REVALIDATE:** actual AKS exec/network의15초 command·30초 snapshot budget과 Pod memory, 기존 controller/AMW joint gate.
새 source의 독립 exact-head review와 별도 paid 결정 전에는 실행하지 않는다. Startup exception·SLO·worker·wave·threshold·승인 횟수는 불변이다.
Campaign22/23 archive/negative/source/counters와 이전 owned cleanup 기록은 그대로이며 cloud 상태를 다시 조회하지 않았다.
Environment11/5 10:30 KST, Foundation/Bootstrap11/6 00:33 KST는 유지한다.
