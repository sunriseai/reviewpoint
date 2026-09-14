# Validation and remaining work

Validated 2026-09-14 against the local reference service. This records technical evidence, not business-policy approval or a production-readiness certification.

## Executed checks

| Check | Result |
| --- | --- |
| Backend tests | 49 passed on Python 3.12 and 3.13 |
| React tests | 12 passed |
| Lint, formatting and strict backend types | Passed |
| Generated contracts | 55 match on both Python versions |
| Documentation links and release-content scan | Passed |
| Isolated source copy | Installed independently; tests passed; frontend assets byte-identical |
| Built wheel | Installed in a fresh environment; offline preparation, API and bundled JS/CSS passed without Node |
| Frontend dependency audit | Zero reported vulnerabilities after updating the test runner |

Two upstream TestClient deprecation warnings remain in test output. The ordinary demo launcher does not use that test client.

## Demonstrated behavior

- The default demo computes its result without a model, starts with one synthetic case and resumes without duplicate submissions or decisions.
- The HTTP walkthrough records Hold, submits corrected work, requires a new assessment, records Proceed and reports a matching simulated handoff. Storage survives restart.
- Profile authoring preserves API-managed checks and advanced settings. Publishing v2 leaves the prior review bound to v1. Consequences use explicit Proceed/Hold/Both associations.
- Service regression coverage includes project/host isolation, permissions, stale tokens, retries, concurrent writes, unknown evidence, failed/interrupted model attempts, invalid citations, expiry, exceptions, concerns, revocation, supersession, history, backup and corruption checks.
- Component tests cover explicit rationale, adjacent feedback, failed-save recovery, accessible action help, evidence inspection, profile editing and API mapping. No test makes a paid model request.
- The executable offline quickstart and all maintained local documentation links are checked automatically. Release scanning covers source, docs, generated contracts and bundled frontend assets.

## Browser evidence

The walkthrough above was performed in the browser through the real API, using only generated local identities and invented data. The initial [desktop review](images/review.png) was captured at a 1200 × 900 viewport. The [phone review](images/mobile.png) uses a 390 × 844 viewport; it shows the reason form immediately beneath the choices and before the recommendation explanation. Both action columns remain readable, with no observed horizontal overflow. Browser console errors/warnings were absent in the tested session.

Publishing new priorities was verified in the UI: guidelines showed v2 while the previously approved review continued to show v1. The simulated host's successful report remained distinct from the human decision. No real host workflow executed.

## Release boundary

The project is prepared for a first public repository review under MIT. It does not configure a remote, publish a package or deploy a service. The release scanner catches known legacy identifiers, credential patterns, private paths and unintended artifacts; a human review of release contents is still necessary for unknown private material.

Production external authentication, shared deployment, distributed execution coordination, enterprise administration and retention/outcome analytics remain future work. Live provider evaluation is opt-in and is not claimed as tested against an external account in this pass. Name and package availability remain unverified.
