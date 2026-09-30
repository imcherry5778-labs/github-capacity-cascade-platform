# P1 local Forgejo platform entrypoints. CI(.github/workflows/local-platform.yml)도 같은 scripts를 사용한다.
#   make static   cluster 없이 source/static/render validation
#   make local    static + fresh cluster up + healthy baseline + P1/P2 regression
#                 + P4 healthy gate / saturation / bounded retry / same-cluster removal + cleanup
#                 (이 invocation이 만든 cluster만 성공/실패와 무관하게 cleanup, 기존/다른 invocation cluster는 건드리지 않음)
#   make up | baseline | verify | down   lifecycle 단계별 실행
.DEFAULT_GOAL := static
.PHONY: tools static up baseline verify down local recovery upgrade

tools:
	scripts/install-tools.sh

static:
	scripts/local-verify.sh static

up:
	scripts/local-up.sh

baseline:
	scripts/local-verify.sh baseline

verify:
	scripts/local-verify.sh runtime

down:
	scripts/local-down.sh

local: static
	scripts/local-run.sh

recovery: static
	scripts/local-recover.sh

upgrade: static
	scripts/local-recover.sh upgrade
