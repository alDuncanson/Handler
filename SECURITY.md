# Security

## Reporting a vulnerability

Use [private vulnerability reporting](https://github.com/alDuncanson/Handler/security/advisories/new)
rather than a public issue. Expect an acknowledgement within a week.

## Supported versions

The latest release on PyPI. Fixes ship as a new release, not as backports.

## Verifying a release

Every release is built by GitHub Actions from its tag, attested, and published
to PyPI with attestations. To check a downloaded wheel came from this repo:

```sh
gh attestation verify a2a_handler-<version>-py3-none-any.whl --owner alDuncanson
```
