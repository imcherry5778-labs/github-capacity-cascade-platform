# 제26차 P9-W2 — CLOSED/invalid (initialize readiness NO-GO) / owned cleanup 완료

**P9 acceptance 미충족. KEDA apply·C3 calibration·freeze·measured C0–C3는 시작하지 않았다.**
[단일 Campaign26 승인](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/issues/47#issuecomment-6620397714)과
[독립 source gate](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/pull/49#pullrequestreview-5761810693)의 paid source는
`d7d963c987ed887b5de40cb22900a95870a87cf8`이다([exact-head CI41748110168](https://github.com/imcherry5778-labs/github-capacity-cascade-platform/actions/runs/41748110168)).
실행 중 paid source는 바꾸지 않았고 retry도 하지 않았다. Owned image manifest digest는
`sha256:6eb99f0fa9a64ef758335c5ca56aec643f14b84d5ea94f5ffaa64934049b4159`(remote = local build)이다.

| 실행 | 실제 소비·결과 |
| --- | --- |
| normal journey | 1, SUCCESS (warmup valid, operation9) |
| public initialize | 1, FAILED `readiness_resource_guard` / `pod_not_ready_or_restarted` (17.956초) |
| healthy journey / KEDA apply·restore | 0 / 0·0 |
| C3 calibration / freeze / measured C0–C3 | 0 / 없음 / 각0 |
| cloud mutation | 10 (모두 owned cleanup 대상) |

## 첫 mutation 전 gate

- Read-only preflight 전 항목 PASS: source·remote·clean, actor/subscription, 4 RG/34 IDs, Owner2, autoscaling 없는 고정2 nodes,
  KEDA/OIDC/Workload Identity enabled, core quota 8/10, C25 UAMI·image tag·임시 role 부재, plan endpoint = AMW query endpoint, reserve.
  AMW의 기존 ServicePrincipal Monitoring Data Reader 1건은 C25 이전부터 있던 Grafana managed identity로 P9 잔여물이 아니다.
- **KEDA-form GET transport probe:** KEDA 2.19 `ExecutePromQuery`와 같은 형식
  (`GET /api/v1/query?query=<QueryEscape>&time=<RFC3339>`)의 canonical scale query(full URL **4726 byte**)가 **HTTP 200**, `success`/`vector`, result 0을 반환했다.
  인증은 operator Entra user Bearer였고 KEDA workload identity가 아니다. 이는 URL 길이 transport만의 확인이며 scaler/HPA/control PASS가 아니다.
  KEDA apply 전에 campaign이 닫혀 실제 scaler 경로는 이번에도 관측하지 않았다.

## 실패 원인 — HAProxy startup DNS race

Initialize는 CPU settling·healthy journey·telemetry 전 첫 readiness/resource guard에서 실패했다. Cleanup 전 read-only 관측:
HAProxy 컨테이너 `restartCount=3`, last termination `Error`(02:01:34Z), 이전 log는
`'server ext_authz/app' : could not resolve address 'ext-authz-sim.p8-shared-gate.svc.cluster.local'` 후 worker exit1, 이후 Running/Ready였다.
C0 render는 하나의 List apply에서 `Deployment/haproxy`(index4)가 `Service/ext-authz-sim`(index7)보다 앞서며, HAProxy `server` 줄은
기본 `init-addr`(시작 시 resolve 필수)이고 resolvers가 없다. Campaign25의 같은 경로는 timing상 restart0으로 readiness를 통과했다.
즉 잠재 startup race이며 strict guard는 restart>0을 정확히 fail closed했다. DNS 전파 시간의 정확한 원인은 UNKNOWN이다.

승인은 initialize ≤1이고 이미 소비됐다. Pod 삭제로 restart를 지우거나 두 번째 initialize, HAProxy 설정/source 변경은 하지 않았다.
Healthy initialization 없이 KEDA/calibration에 진입하지 않으므로 **NO-GO로 Campaign26을 닫았다**. Campaign27은 시작하지 않았다.

Paid source 변경 없는 operator 교정 1건: `access`에서 kubelogin/kubectl이 C25 private PATH에만 있어 같은 binary를 복사했고 임시 role은 재생성하지 않았다.

## 원복·계수

같은 parent의 `close → cleanup()`에서 `CUSTOM_remove`, `mesh_restore`, `namespace_remove`, `normal_fixture`, `stable_integrity`, `image_remove`,
`AMW_role_remove`, `UAMI_FIC_remove`, `AKS_role_remove`, `ARM_final`, `forward_close` 모두 `complete=true`, `cleanup-final` complete/errors=[],
`operator_parent_exit cleanup_complete=true`다. Healthy fixture와 KEDA restore는 생성/patch되지 않아 해당 없다.
Normal PAT DELETE204·reuse401·login401, 34 IDs 불변·Owner2·fixed2 nodes·owned role 부재, owned image digest 부재, private registry credential 사본 제거와 logout.
02:05:38Z 독립 read-only 재확인: 34 IDs, C26 UAMI/image tag/임시 AKS role 부재, Owner2, nodes2. Driver/forward 종료, lock 해제.
Campaign26 owned cleanup만의 결과이며 global zero residual 선언이 아니다.

누적(Campaign25 누적 + Campaign26): **campaign26 / initialize 시작23 / healthy13 / started-invalid calibration9 / measured 각0 / KEDA actions9/9**.
Campaign22–25는 재분류하지 않는다. Resource hold 약6분, billing GET0, actual 비용 UNKNOWN.
Environment 11/5 10:30 KST, Foundation/Bootstrap 11/6 00:33 KST를 유지했다.

**다음 gate(새 승인 필요):** HAProxy가 target Service DNS 이전에 시작하지 않도록 하는 교정이 필요하다. 후보는 Service-first 적용 순서 또는
HAProxy `init-addr`/resolver 설정이며, 후자는 HAProxy 동작 변경이라 source review가 필요하다. 어느 쪽이든 새 initialize가 필요하므로 새 명시적 paid 승인과 독립 review 없이는 실행하지 않는다.

[execution](execution.json), [raw index](raw-index.json), [sanitized archive](raw-evidence.tar.gz)를 함께 본다.
공개 20개 file roundtrip과 원본 UUID/IP·resource name·private host·JWT·subscription·private-path scan 0을 확인했다.
원본 raw는 local append-only로 보존하고 private harness·diagnostic는 SHA256만 기록했다. Credential/kubeconfig/journey 디렉터리는 제외했다.
