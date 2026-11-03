# P9 제21차 — initialize 실패 / CLOSED / owned cleanup 완료

실행 source는 `2bccb693f25dd1add56650b1a1e1ac1398de2504`다. [제21차 사용자 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#issuecomment-6596832794)과 [exact-source review](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/41#pullrequestreview-5747912114)에 따라 같은 Mac/branch/#41에서 실행했다. Paid source 변경은 없다. **Campaign21 CLOSED/invalid, P9 acceptance 미충족**이다.

## 실제 blocker

Normal과 healthy client journey는 각각9 operations/9 attempts valid/success다. Public initialize1·healthy1을 소비했으며 retry0다. CPU poll8, journey 이후 telemetry poll5, Prometheus request21/25, query maximum1.134375s였다. CPU 준비는 처음 성공했으나 telemetry와 현재 CPU freshness를 동시에 입증하지 못해 initialize가 `healthy initialization polling timeout; do not repeat journey`로 종료됐다. Internal telemetry75초 기한 실패이며 outer840초 timeout을 소진한 실패가 아니다.

| CPU 관측 UTC | CPU sample age(s) | CPU 판정 | AMW |
| --- | ---: | --- | --- |
| 06:31:58.223969 | 31.224 | pending | uninitialized |
| 06:32:13.060213 | 46.060 | pending | uninitialized |
| 06:32:29.928454 | 62.928 | pending | uninitialized |
| 06:32:43.952315 | 20.952 | ready | uninitialized |
| 06:32:58.171495 | 35.171 | pending | observed |

마지막 AMW 응답은 실제 guarded row0과 단일 UID의 rate/count4가 존재했다. Empty를0으로 바꾸지 않았다. 첫4회 rate는 `[]`; 뒤3회에는 active/timestamp/count1이 있었고 마지막에 count4가 관측됐다. 그때 CPU timestamp는06:32:23Z, window53.275초, age35.171초>기존 initial C0 CPU freshness30초였다. HPA recovery/Ready 이후 window 조건은 기록됐지만 현재 CPU readiness는 pending이다. CPU가 ready였던 직전 poll의 AMW는 uninitialized였으므로 둘을 이어 붙이지 않았다.

마지막 signal의 실제 client evaluation clock/event/hash와 canonical/envelope provenance를 원본/공개본에서 strict parser로 대조했다. CPU 관측 UTC−sample epoch도 age와 일치한다. 미관측 중간 overlap, AMW backend ingestion atomicity, Metrics API export/cache cadence 원인은 unknown이다. 완전한 failed guard를 재구성하거나 제18/19/20차 원인을 소급 확정하지 않는다.

실패한 initialize는 재호출/유효화하지 않았다. **KEDA IAM/SA/restart·actual scaler auth·calibration/freeze·C0–C3 measured 모두0**이다. 새 C3 resource150초와 mitigation240/recovery180초 후보는 실제 실행되지 않았다. 이번 결과는 이를 검증/부정한 evidence가 아니다. 실패 경계가 초기 C0 준비의 기존30초 CPU/75초 telemetry joint gate임을 구분한다.

## 실행 경계와 원복

Actual actor/subscription·native Entra user·exact AKS1 임시 RBAC, 4RG/34개 ARM IDs·고정2노드·AKS1.36.4/asm-1-30·PG17/ACR Basic·KEDA2.19.0-25를 확인했다. Non-admin fixture/PAT2개, dedicated user kubeconfig, action별 named Secret projection과 fake-secret/output 경계 테스트를 사용했다. 기존 보안 회전·global login·cost GET은 반복하지 않았다. DB app-role hostname/CA verify-full/TLS/read-only SQL, target-stage actual admission/headroom을 통과했다.

Image는 source-bound OCI index `sha256:64d411a442249893352eea4fc066692c75175849e923991e75494ffb68f5e523`이며 linux/amd64 executable+연결된 attestation 두 child를 검증했다. Docker29의 local image ID가 config가 아닌 index descriptor인 점을 실제 protocol로 교정해 index·revision label·rootfs/config를 대조했다. 보호 Docker config의 기존 Mac socket/buildx 선택, CLI option/local parser 오류를 같은 source·unconsumed stage에서 교정했고 source/initialize retry는 없었다. Noninteractive parent의 mutation 전 EOF도 raw에 보존했다. 실제 mutation/forward는 단일 parent가 소유했다.

CUSTOM exact UID 제거→shared CM UID/data guarded 복원→namespace/Secret/controls 제거, stable Argo/Pod/Deployment/CSI/PVC/PV 및 named admin/DB Secret UID/value 비교가 완료됐다. 이 비교는 같은 parent memory에서 수행했고 full spec/Secret pair를 raw로 emit하지 않아 독립 full-pair replay는 주장하지 않는다. Initial/final native verify 각각1회, integrity4개 pass와 기존 console-only paths 진단의 정확한 분류다. KEDA mutation은 없었다.
PAT2개는 exact ID DELETE204·reuse401·list0·login401, 계정/저장소는 삭제하지 않았다(별도 post-cleanup SQL 재조회 없음). Image는 live reference/shared tag/foreign parent를 확인하고 owned index+child3개만 삭제·각 MANIFEST_UNKNOWN, local source tag 제거를 확인했다. 임시 AKS role RoleAssignmentNotFound, 원래 Owner2개·4RG/34 IDs 보존, owned forward TERM/wait(-15), parent exit0/cleanup_errors=[]다. Foreign image metadata는 삭제하지 않았다. Global Azure cache는 유지하며 전체 zero residual/secure erasure는 주장하지 않는다.

누적 **campaign21 / initialize18 / healthy9 / started-invalid calibration6 / measured 각0 / KEDA apply·restore6/6**. 이전 campaign20 CLOSED/invalid·미사용 권한 소멸과 과거 archive는 그대로다.
기존 retained-resource/lag/overlap/cleanup projection290.3567에 이번 bounded variable estimate5를 연결한 planning295.3567을 보존한다. USD290 자체를 NO-GO로 쓰지 않았고 새 숫자 cap/자원/기간을 만들지 않았다. 실비/잔액은 shared/delayed/unknown이며 billing GET0이다. Whole reserve8045초와 owned cleanup1800초를 확인했고 Environment `2026-11-05T01:30:00Z`/Foundation·Bootstrap `2026-11-05T15:33:00Z`를 유지했다. 추가 campaign·retention·teardown·merge/P10은 없다.

[execution](execution.json), [comparison](comparison.json), [validation](validation.json), [raw index](raw-index.json), [sanitized selected raw archive](raw-evidence.tar.gz)를 함께 본다. 원본 raw는 append-only 보존하고 source exact-head CI는 재사용한다. Evidence HEAD/CI와 실제 검증 범위는 #41 결과 comment에 연결한다.
