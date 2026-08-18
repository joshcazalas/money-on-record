# Engineering issue index

GitHub Issues is the source of truth for deferred work:

- [#1 — Decide the first application architecture](https://github.com/joshcazalas/money-on-record/issues/1)
- [#2 — Bootstrap AWS organization, environment accounts, state, and GitHub OIDC](https://github.com/joshcazalas/money-on-record/issues/2)
- [#3 — Add low-cost PR previews and sanitized Terraform plan comments](https://github.com/joshcazalas/money-on-record/issues/3)
- [#4 — Implement intentional semantic releases and production deployment](https://github.com/joshcazalas/money-on-record/issues/4)
- [#5 — Automate dependency and toolchain update PRs](https://github.com/joshcazalas/money-on-record/issues/5)
- [#6 — Define the long-term dependency vulnerability severity policy](https://github.com/joshcazalas/money-on-record/issues/6)
- [#7 — Configure moneyonrecord.org DNS, TLS, and environment hostnames](https://github.com/joshcazalas/money-on-record/issues/7)
- [#9 — Complete L0 evidence review and pass/pivot decision](https://github.com/joshcazalas/money-on-record/issues/9)

Repository governance was configured during bootstrap. The active `Protect main`
ruleset requires pull requests, one code-owner approval, resolved review threads,
the six CI jobs, and exactly one release-impact label. Josh has a pull-request-only
bypass for self-authored changes. Merge commits are the only enabled merge method,
and status checks use the loose policy so branches do not need to be updated before
merge.
