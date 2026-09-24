# P1 local Forgejo platform entrypoints. CI(.github/workflows/local-platform.yml)도 같은 scripts를 사용한다.
#   make static   cluster 없이 source/static/render validation
#   make local    static + fresh cluster up + runtime verification + cleanup (실패해도 cleanup)
#   make up | verify | down   lifecycle 단계별 실행
.DEFAULT_GOAL := static
.PHONY: tools static up verify down local

tools:
	scripts/install-tools.sh

static:
	scripts/local-verify.sh static

up:
	scripts/local-up.sh

verify:
	scripts/local-verify.sh runtime

down:
	scripts/local-down.sh

local: static
	scripts/local-up.sh && scripts/local-verify.sh runtime; rc=$$?; scripts/local-down.sh && exit $$rc
