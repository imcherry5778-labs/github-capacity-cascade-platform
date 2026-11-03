# P9-W2 — cost-free startup/ring candidate 검증

Source commit `5360df5ef93647dd4e9374232440cea32c2aa23f`의 local 검증이다.
최종 PR HEAD는 이 source/test file hash와 같은지 확인한 뒤 PR #49 결과 comment에 기록한다.
**Azure API·credential 조회/변경·publish·paid workload는 수행하지 않았다. P9 acceptance 미충족이다.**
Campaign22·23 archive/source/negative/횟수는 불변이며 Campaign23은 CLOSED/invalid다.

## Pinned Docker 실제 관측

`docker.io/library/haproxy:3.4.6-alpine@sha256:7af8255207ee9964ccb4eec8ce4b7a40b777769665e3ae83897fb01b24d8a43a`,
HAProxy `3.4.6-56332c5`, Linux amd64, BusyBox1.37.0 `nc`를 확인했다.
Generated C0–C3 config의 backend 주소만 local HTTP stub으로 바꾸고 HAProxy CPU250m/memory256Mi cap에서 실행했다.
Frontend/backend/C2 queue policy와 log-format은 candidate render 그대로다. C1은 fd@1을 FIFO로 막는 별도 transport negative 조건이다.

| Arm | Client responses / ring rows / drained frontend stot | `%lc` duplicate / gap | process DroppedLogs | PR / sQ |
| --- | --- | --- | --- | --- |
| C0 | 3300 / 3300 / 3300 | 114 / 114 | 248 | 0 / 0 |
| C1 | 3300 / 3300 / 3300 | 77 / 76 | 2961 | 0 / 0 |
| C2 | 3428 / 3428 / 3428 | 79 / 79 | 315 | 3234 / 135 |
| C3 | 3300 / 3300 / 3300 | 48 / 48 | 108 | 0 / 0 |

Total13328 response와 row 수가 같고 ring dropped0, OOMKilled=false였다.
중간 capture의 prefix·Pod UID/PID/start-time·request counter 중복을 검사했다. 최대 CLI 수집0.887초(<15초)였다.
Local connect-timeout `sC`도 발생했으며 모든 row/status를 보존했다. **이는 capture proof이며 healthy/native auth/SLO PASS가 아니다.**
Exec wget readiness 전후 check log가 같았다. Raw의 native boundary는 `captures[0]`과 마지막 `haproxy.frontend` 포함 capture이고,
그 뒤 마지막 capture는 readiness-only 불변 확인이다. 실제 native counter를 뒤의 capture에 복사해 새 관측으로 만들지 않았다.

초기 prototype은 `%lc`를 유일 연속 ID로 취급해 실패했다. 그 실제 CLI response도 archive에 보존했다.
후속 complete capture에서도 위 중복/gap이 나타나므로 `%lc`만으로 완전성을 증명하지 않는다.
`%rt`의 gap도 별도 stats frontend 요청 때문에 채우지 않는다. Candidate는 실제 check frontend lifetime counter와 row 수의
drained equality 및 prefix/identity/capacity 검증을 함께 요구하며 누락 수를 log row로 합성하지 않는다.
이 발견은 **Campaign23의3036 대3139 실제 row 차이를 없애지 않는다. 정확한 loss hop은 UNKNOWN이다.**

4KiB tiny-ring negative는 실제 frontend121건 중20개 row만 남았다. 원래 값을 유지한 `400/CR/Tw=-1`1개도 있었고
candidate guard는 `incomplete at drained frontend boundary`로 거부했다. 이 시험은 source의4MiB ring을 실제로 줄여 적용한 Azure 실행이 아니다.

[HAProxy logging manual](https://cdn.haproxy.com/documentation/haproxy-configuration-manual/latest/#8)과
[CLI show events](https://docs.haproxy.org/3.4/management.html#9.3-show%20events)는 fd logging의 drop 가능성과 in-process ring/CLI를 설명한다.
참고 문서는3.4 계열의 current manual이며 정확한3.4.6 image 동작은 위 local 실행으로 별도 확인했다.
`DroppedLogs`는 process diagnostic이고 row equality proof가 아니다. Local fd@1 backpressure 재현으로 Azure103건의 원인을 확정하지 않는다.

## Candidate 판정과 남은 경계

- **DECIDED (candidate)**: bounded C3 startup의 실제 False/FailedGetExternalMetric를 degraded로 보존한다.
  Same HPA UID/owner/spec/status hash·자체 monotonic GET clock, 기존 Ready90/AMW75/resource joint150초와 strict freshness/two-sample,
  원래 budget 안의 실제 usable metric·True/ValidMetricFound joint 관측을 모두 요구한다.
  Persistent/다른 error·초기화 뒤 실패·provenance 누락은 invalid다. Degraded 구간은 controller health/convergence/recovery proof가 아니며
  confounder review에도 정확한 제외 목록을 요구한다. Earlier HPA와 later AMW를 같은 evaluation으로 만들지 않는다.
- **REVALIDATE**: native AKS exec/Pod memory·HPA/scaler/AMW 독립 clock과 실제 future joint 관측. Actual scaler cause도 UNKNOWN이다.
  새 source의 독립 exact-head 검토 및 별도 paid 결정 전에는 campaign24를 실행할 권한이 없다.
- **DEFERRED**: Campaign23 cleanup parser는 제거된 one-off operator다. Maintained caller가 없어 새 parser/framework를 만들지 않았다.
  Initial error3개와 targeted cleanup complete/errors=[] 기록을 유지한다. 다음 operator는 empty successful delete와
  case-insensitive manifest-unknown/실제 absence를 구분해야 한다.

P9 unittest137개 PASS(skipped3: Docker opt-in2개와 기존 skip1개), exact source commit의 Docker opt-in2개는 실제 PASS(52.565초)다.
Mac `make static`은 BSD stat 뒤 GNU coreutils로 진행했으나 기존 Linux bootstrap harness의 `flock` 부재에서 막혔다.
관련 source를 수정하지 않았고 최종 Linux exact-head CI 결과는 PR comment에 연결한다.
Recovery0.2초·worker12·wave/demand·threshold는 불변이며 historical639/884 negative도 그대로다.
Local owned containers를 제거했다. 이번에는 cloud 상태를 다시 조회하지 않았고 이전 Campaign23 owned cleanup 기록을 유지한다.

[Execution/limits](execution.json), [raw index](raw-index.json), [원본 local raw9개](raw-evidence.tar.gz)를 함께 본다.
Source/test hash·member size/SHA256·archive roundtrip과 credential/private-path/publication scan을 확인했다.
원본 local observation을 그대로 보존했고 row redaction/filter/normalization이나 historical 재서명은 없다.
