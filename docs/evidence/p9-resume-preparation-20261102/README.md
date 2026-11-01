# P9-W1 승인 전 재개 준비 / 다음 단일 통합 승인안

**제15차 미실행·미승인 / P9 acceptance 미충족.** 이 문서는 실행 승인 요청안이다.
기존 PR #41 / `feat/p9-mitigation-recovery`에서 준비만 했다. 독립 review·실행 승인·merge는 별도다.
시작 HEAD `d0d16cf7ba57e7cc6b589b442f03cfe0ed998735`, actual main
`52ada7f2a56a9ea5ae4b32b6f23ee566d47ac9bb`를 확인했다. Branch/PR/worktree 교체는 없다.
Orca에는 이 context 하나와 terminal0, 이전 operator context의 별도 writer가 없었다.

## 이번에 확인한 사실

- 시각 첫 관측 **2026-11-02 07:09:13 KST**. Azure GET은 **07:10:20–07:11:01 KST** 시작 시각별로
  [management.json](management.json), [cost.json](cost.json)에 기록했다. 완료 시각으로 확대하지 않는다.
- AKS Running/Succeeded, Kubernetes1.36.4, managed Istio asm-1-30, 고정2×Standard_D4s_v4,
  autoscaling OFF. PG17/Standard_D2ds_v5/32GiB/Ready/HA disabled, 기존 ACR/AMW/LAW/Disk inventory를 읽었다.
  첫 DB GET의 잘못된 이름은 ResourceNotFound였고 inventory의 actual 이름으로 교정한 GET은 성공했다.
- Regional cores 및 DSv4 quota 각각8/10, VM count2/25000. 이것은 Kubernetes live headroom이 아니다.
- 기존 Entra user의 subscription Owner assignment2개와 세 RG의 management `actions=['*']`를 읽었다.
  AKS는 managed Entra/Azure RBAC=true이며 `dataActions=[]`. **Kubernetes data-plane 권한은 not verified**다.
  임시 AKS role 재부여·credential 발급/refresh·admin credential·권한 확대를 하지 않았다.
- Subscription inventory GET38개 resource 중 기존 project 자원을 보존한 관측이다. Namespace/Pod/Argo/
  CRD/SA/KEDA/Secret/PAT/image 내부 상태나 cleanup 재검증·zero residual을 뜻하지 않는다.
- Cloud mutation/load/port-forward/normal/healthy/preflight/calibration/measure는 모두 미실행이다.
  DB `verify-full`, target-stage live headroom, native-auth200과 실제 signal/KEDA/collection은 미래 live gate다.

## Operator 최소 보완과 직접 검증

제14차 임시 operator 사본은 당시 cleanup으로 제거됐다. 저장 이력에서 forwarding 호출 부분만 확인했다.
별도 명령의 `Popen`에 stdin/session 분리와 campaign 중 poll/wait 기록이 없었다는 기존 진단을 재사용한다.
Sentinel transport와 별도 monitor failure의 실제 원인·인과는 여전히 unknown이다.

기존 [P9 source](../../../scripts/azure-mitigation.py)의 `owned_forward()`에 그 operator가 사용할 경계를 둔다.
새 harness/controller/CLI entrypoint를 만들지 않는다. Existing exact-source `approval_gate()` 뒤에만 spawn하며
campaign 부모가 context 종료까지 handle을 보유한다. stdin=DEVNULL/start_new_session=True, private log는
0600/exclusive-create다. PID·spawn 시작 UTC·Pod UID·source SHA를 고정하고, 단계 checkpoint와1초 poll,
마지막 bounded TERM5s→필요 시 KILL5s/wait return code·intentional stop 요청·이미 종료 여부를 기록한다.
argv/stderr/credential/private log path는 emit하지 않는다. Process 생존은 semantic200의 대체 근거가 아니다.

다음 승인 operator는 기존 단계들을 **하나의 campaign 부모**에서 실행하고 다음 형태를 적용해야 한다.
아래는 연결 형식이며 지금 실행한 기록이 아니다. `emit`은 기존 append-only operator journal writer다.

```python
with m.owned_forward(identity, plan, approval, ledger_rows, actual_forgejo_pod,
                     private_log, emit) as forward_check:
    # 기존 normal/healthy/KEDA/full configuration 준비와 fault 수렴 절차
    forward_check('fault_converged')
    # 같은 actual Pod UID/loopback13000의 non-admin native-auth semantic200
    # 및 영향받는 signal/normal/healthy/KEDA/collection gate 확인
    forward_check('before_measure')
    # 기존 measure entrypoint를 child로 실행; 부모 watcher는 실행 중에도 poll
    # 다음 arm 전 UID/native/signal 재검사, 마지막 owned cleanup까지 같은 부모
```

Local real-child 검증은 stdin EOF, 독립 session, 단계·실행 중 poll, 예외 cleanup,
exit7 차단/회수, 정상 stop/wait를 확인했다. Mock 검증은 TERM timeout→KILL/wait와 비민감 기록,
기존 log 덮어쓰기 및 approval 거부 시 spawn 부재를 확인했다.
Live kubectl/port-forward 또는 실제 승인 operator 전체가 검증됐다는 주장은 없다.
[validation.json](validation.json)은 직접 검증과 source 파일 hash를 연결한다.
Source 변경 HEAD `f16d70911c52c52b52408a5c67b26140c6677bc0`의 [자동 CI](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41356125476)는
full-runtime/success다. P9 회귀84개와 local/recovery/upgrade/ownership/cleanup이 실제 실행되어 성공했다.
후속 문서 HEAD의 check 결과는 PR 결과 comment에 별도 연결하며 Azure runtime/독립 review로 확대하지 않는다.

## 단일 통합 실행 승인 요청 범위

아래 **전체**에 대한 별도 명시 승인 전 paid 경로는 NO-GO다. 과거 승인 URL·USD180을 재사용하지 않는다.
대상 source는 이번 변경을 포함한 **최종 PR exact HEAD**이며 결과 comment에 SHA/자동 CI URL을 고정한다.
Monitor 진단 `f165dfb`의 변경 없는 독립 review는 재사용하고, 이번 delta는 새 독립 review가 필요하다.
작성자 self-review와 최종 merge review는 실행 전 독립 review를 대신하지 않는다.

1. 기존 inventory만 재사용하는 **단일 제15차 campaign**. 기존 [권한·mutation·원복 범위](../../p9-mitigation-recovery.md#이전-통합-승인-범위--c06-preflight-이력)를
   이번 source에 새로 승인 요청한다: exact AKS resource의 임시 Entra-user RBAC Cluster Admin assignment1개,
   user-auth 보호 kubeconfig, 기존 stable Secret version 한정 읽기/rotation 생략, disposable non-admin fixture2/PAT2,
   기존 ACR의 `ext-authz-sim:<approved-source-sha>` tag1개 publish/소유 image cleanup,
   P9 namespace/fixture/fault/CUSTOM/shared CM guarded overlay/restore, 전용 UAMI/FIC 및 AMW1개의 Monitoring Data Reader.
   새 node/server/Disk/PVC/registry, autoscaling 변경, stable Argo resource mutation, admin load는 제외한다.
2. Actual KEDA owner/다른 ScaledObject 영향 확인 뒤 필요할 때만 SA annotation/apply restart≤1,
   원래 template/annotation restore restart≤1. 과거 누적 apply/restore3/3에 이번 최대1/1을 더해4/4 이하다.
   Shared managed controller 영향은 experiment quota 밖의 명시 위험이다. 다른 workload 영향이면 mutation 전에 중단한다.
3. DB hostname/CA를 통한 **verify-full** 및 read-only SQL, target-stage **live headroom 선행**,
   초기 normal1/healthy journey1, native/controlled deny/path와 실제 KEDA scaler auth·단일 owner·full configuration/
   signal/collection gate를 유지한다. Fault 수렴 뒤 **measure 직전 같은 non-admin loopback semantic200**을 재확인한다.
   새 Pod/identity/image/plan의 actual 증거는 이 승인 실행에서 수집하며 제14차 positive로 대체하지 않는다.
4. Source/actual image digest/cluster UID/preparation plan hash를 결합하고, calibration≤2 이후 reviewed calibration으로
   최종 source/configuration/demand를 freeze한다. Measured는 C0→C1→C2→C3 각≤1. 최대6run, run≤600s
   (mitigation+recovery≤540s 및 drain/수집60s), logical≤16,200/client attempts≤31,752.
   Native sentinel 최대 약3,600회와 정상/deny/telemetry 요청은 별도 실제 계수한다.
   Image digest/actual identity/plan hash는 **아직 없음**. 승인된 publish/준비 후 이를 기록·검사하기 전 load는 금지다.
5. 같은 source의 measure 전 operator forwarding 복구는 허용 요청한다. 실패 process/log를 보존하고 exact child를 회수한 뒤
   새 private log/Pod UID로 소유 forwarding을 재준비하며 영향받는 native/signal/UID gate를 다시 확인한다.
   시작한 invalid calibration은 소비하며, 이번 첫 calibration 실패 뒤 최대1회만 남는다. 남은 횟수·비용·reserve 안에서만 진행한다.
   Healthy journey intent가 기록되면 재호출하지 않는다. 자동 retry·measured retry·source-changing recovery는 요청하지 않는다.
   Source-changing same-ledger 재개는 현재 gate가 거부한다. 필요 시 source 수정/cost-free 검증만 하고 새 binding/review/승인 전 paid 경로를 보류한다.
6. Continuing-demand recovery/SLO/accounting/confounder 검토 후 기존 순서의 P9-owned cleanup, final native verify1,
   exact PAT/image/IAM/namespace/forwarding/보호 사본 회수와 stable 보존 evidence를 남긴다.
   실패 한 번만으로 campaign 전체 종료를 강제하지 않지만 safety/ownership 회복 불가·한도/기한 소진이면 owned cleanup으로 종료한다.

[accounting.json](accounting.json)은 기존 summary에서 누적을 추출했다. 과거14 campaign의 initialize11,
healthy journey3, calibration2(제10·14차 각각 invalid1), measured 각0을 보존한다.
다음 **추가 승인 요청**은 campaign1/initialize1/healthy1/calibration≤2/measured 각≤1이므로 누적 최대
campaign15/initialize12/healthy4/calibration4/measured 각1이다. 과거 ledger의 미사용 allowance를 이전하지 않으며
새 campaign allowance를 승인 없이 생성하지 않는다. 현재 새 실행 허용량은 모두0이다.
단일 campaign ledger는 동일 SHA만 허용하며 이전14 raw/ledger/비용/index는 그대로 남긴다.

## 비용·기한 판단과 필요한 결정

GET Usage Details164행/nextLink 없음의 billingCurrency=KRW를 날짜/RG별 집계했다.
두 RG posted **KRW141,317.0840010261**, Foundation/Bootstrap 포함 returned 합계 **KRW141,431.5409806095**다.
제14차 마지막보다 posted **KRW10,914.0384468222** 증가했다. 이는 해당 query surface의 shared/delayed 금액이며
P9 incremental actual/현재 잔액은 **unknown/not verified**다. 11월1일은 partial posted다.
과거 CostManagement POST aggregate의 현재 재조회를 하지 않고 허용된 GET 결과만 사용했다.
[Microsoft Usage Details GET](https://learn.microsoft.com/en-us/rest/api/consumption/usage-details/list?view=rest-consumption-2024-08-01)의
현재 응답 필드를 사용한 일회성 관측이며 새 dependency를 도입하지 않는다.

Ninth baseline KRW49,306.6929280465를 초기화하지 않는다. 기존 보수적 모델의 posted delta 전체+
최대 full-day KRW30,388.0207611084×50h/24(중복 포함)+기타 USD5+이전 variable USD15를
planning stress **1,200KRW/USD**로 환산하면 **USD149.4323**, 이번 variable **USD5를 별도 가산하면 USD154.4323**다.
이는 시장/청구 환율·세금·실제 volume·확정 청구/잔액이 아니다. Image0.2GB/logs1GB/metrics1M/egress1GB와 buffer의
기존 가정을 재사용했으며 새 retail 수집/volume 측정은 없다. 공유 비용/미반영/환율 위험을 포함한
**누적 세전 검토상한 USD180을 이번 실행에 새로 승인 요청**한다. USD180 추가 충전·잔액 또는 billing hard cap이 아니다.
새 actual/estimate가 상한을 넘거나 분리 불가능한 비용 위험이 커지면 추가 run 전에 판단을 요청한다.

현재 Environment **11월2일10:30 KST**, Foundation/Bootstrap **11월3일00:33 KST**다. 요청 연장은 **0h**다.
8045s = 준비/normal/게이트 여유1800 + initialization840/kill5 + 최대6×(run540+drain60) + rollback1800을 확보한다.
초기 관측의 Environment 잔여는12,047s, 전체 reserve 이후4,002s이며 준비·CI·독립 review·승인 대기는 이 여유를 소비한다.
**첫 paid mutation 전 새 시각으로 잔여>8,045s를 확인해야 하며, 기존 기한이면 시작은08:15:55 KST보다 빨라야 한다.**
각 initialize/run에서도 source의 initialization/run/drain60/rollback30m strict deadline gate를 적용한다.
07:09 관측이나 이 문서 작성 시각을 실행 허가 시각으로 고정하지 않는다.

승인/검토가 늦어 reserve를 못 맞추면 이번 계획은 **실행 NO-GO**다. 그때만 별도 결정 참고로
Environment **+6h→11월2일16:30 KST**를 검토할 수 있다. Two-RG 유지비 가정은 추가 약USD6.331,
Foundation/Bootstrap 기존 기한은 그보다8h03m 뒤여서 동일 연장이 필요하지 않다.
이 경우에도 source의 hard deadline은10:30 그대로이므로 **명시 기한 승인 후 최소 deadline 교정·새 exact SHA/CI/독립 review/
실행 binding 승인**이 필요하다. +6h를 지금 요청/적용하거나 자동 연장·전체 teardown하지 않는다.

사용자 결정은 위 source의 독립 review 뒤 **새 권한/mutation·단일 campaign 횟수·누적 비용상한·기존 기한 내 실행·
shared KEDA 영향과 같은-source bounded operator 복구 범위**에 대한 하나의 통합 승인이다.
준비 완료는 freeze/네 arm 비교/recovery/원복 runtime evidence나 P9 acceptance를 충족시키지 않는다.
