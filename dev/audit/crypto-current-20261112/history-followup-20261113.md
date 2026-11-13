# Historical destination follow-up — 2026-11-13

Candidate only: not merged, deployed or enabled. No real receiving destination,
invoice, balance, payment setting, ledger or Production container was changed.

The former blanket rejection of any historical invoice is replaced in the
Production activation endpoint by a fresh, locked history review while issuance
remains disabled. Read-only previews are available in the owner Mini App and
private Bot. Neither a preview nor a mutable scan diagnostic authorizes rotation.

- Historical TON aliases are matched by account identity without rewriting invoice strings.
- Scans use an explicit UTC start and fixed end, bounded pagination and strict parsing.
  Missing/malformed data, unsupported finality, provider errors, duplicate or unassigned
  transfers and incomplete invoice/chain/ledger matches block activation.
- Credited invoices require the original wallet ledger reference, user, direction,
  reason and amount, plus a matching confirmed chain transfer. No payment is retried.
- Open/review invoices and the payment grace window still block rotation.
- Activation retains the old destination and full review scan start atomically with
  the new version. Previously retired addresses cannot be selected again.
- Retired destinations remain scanned even without open invoices. Their transfers
  bypass automatic crediting and go to an idempotent manual review inbox. Existing
  invoice/ledger rows are not rewritten. Scan failures do not clip historical coverage
  into an apparently successful recent window.
- Provider error output is limited to its type; keys, raw URLs and financial identifiers
  are excluded from the review response. Bot history output requires a private chat.

## Executed validation

| Suite | Result |
|---|---|
| Full financial Backend | 289 passed, 68 subtests; 4 opt-in skipped |
| Full financial Bot | 73 passed, 12 subtests |
| Disposable MySQL owner flows + concurrency | 9 passed |
| JavaScript | All 10 suite files passed |
| Chrome owner wallet interface | Passed; two mocked writes, zero real network requests or JS errors |

MySQL tests use the existing internal Docker network and the hard-gated
`davarna_wallet_rotation_test` database. The local disposable database was stopped
after the run. Initial attempts exposed a database startup race and uncached MySQL
authentication without the optional client cryptography package. The harness now
waits for readiness and warms the fixture's authentication cache using the MySQL
client. The old SQLite proposal fixture lacked invoice tables; those tables were
added. The former blanket-history rejection test now supplies an explicitly
unreconciled review; its 409 and no-rotation assertions remain. Separate real-table
tests demonstrate the new permitted and rejected cases. No assertions were disabled.

A real-provider **read-only** assessment ran via stdin with the configured providers
and a read-only SQL transaction at 2026-11-13 13:23 UTC. Both providers returned
complete empty incoming-transfer responses across the existing invoice windows;
the reviewer reported no discrepancies. No new code was installed. This is an
observation from those providers at that time, not a proof against later/index-delayed
transfers, and it does not validate parsing of nonempty live responses. The immutable
retired-address watch and strict failure behavior remain necessary.

Provider references used for interval and pagination parameters:
[TON Center transactions](https://docs.ton.org/api/v3/blockchain-data/get-transactions)
and [TronGrid TRC20 account history](https://developers.tron.network/reference/get-trc20-transaction-info-by-account-address).

## Remaining review and rollout gates

PR #53 still requires independent review and explicit financial merge/deployment
approval. Real destination changes additionally require the owner's exact destination
and confirmation; none was requested or performed here. No migration is added by
this follow-up. The provider contract is deliberately strict: an unfamiliar finality
or malformed response blocks instead of being guessed. The bounded full-history
scan can require a separately reviewed backfill plan on high-volume addresses.

Application rollback after a real rotation must keep scanning all retired destinations;
merely disabling the versioned-address gate can select the original environment
address and is not a safe rollback. Historical invoice and ledger rows must never
be deleted to bypass a readiness failure.
