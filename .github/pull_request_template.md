## 무엇을 변경했는가

<!-- 변경 내용을 짧게 설명한다. -->

## 왜 필요한가

<!-- 해결하려는 문제와 현재 milestone/unit의 목표를 설명한다. -->

## Scope / non-goals

<!-- 이번 PR이 포함하는 범위와 의도적으로 하지 않는 범위를 적는다. -->

## 어떻게 검증했는가

<!-- 실제 실행한 command/test/CI/evidence를 적는다. 실행하지 않았다면 이유를 적는다. -->

## Acceptance

<!-- 해당 work unit의 acceptance criteria를 어떻게 만족했는지 적는다. -->

## 비용 / external side effect

<!-- Azure resource, DNS, identity, external service 등 side effect가 있는지 적는다. -->

## 남은 문제 또는 의도적인 한계

<!-- 없으면 "없음"이라고 적는다. -->

## 체크리스트

- [ ] 한 PR이 가능한 한 하나의 capability에 집중한다.
- [ ] 합의된 milestone scope 밖 capability를 선제 구현하지 않았다.
- [ ] 관련 upstream/version contract를 필요한 범위에서 다시 확인했다.
- [ ] 직접 영향받는 test/static validation을 실제 실행했다.
- [ ] secret, credential, kubeconfig, Terraform state, private path를 포함하지 않았다.
- [ ] normal test와 reliability experiment ownership을 섞지 않았다.
- [ ] Azure 비용이 발생하는 action은 명시적 승인 없이 실행하지 않았다.
- [ ] 문서 claim이 실제 검증 수준을 과장하지 않는다.
