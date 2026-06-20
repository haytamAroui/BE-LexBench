# Security Policy

## Supported versions

`be-lexbench` is a research-stage benchmark harness. The current development line (`main`) is the only supported version. No backport patches are issued for older tags.

## Scope

This policy covers:

- The scoring harness (`harness/`) and its dependencies
- The CI/release pipeline (`.github/workflows/`)
- The item schema (`schema/eval_item.schema.json`)

It does **not** cover:

- The gated item bank
- Third-party model endpoints or APIs that you point the harness at

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately through GitHub's private vulnerability reporting for the `be-lexbench` repository. We aim to acknowledge reports within **3 business days** and provide a resolution timeline within **10 business days**.

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce or a minimal proof-of-concept
- Which version / commit you tested against
