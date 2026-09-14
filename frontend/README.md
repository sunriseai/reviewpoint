# Reference UX

React, Tailwind and Vite render Reviews, Risk guidelines and secondary Settings. All policy and persistence authority stays in the service. The reusable [ReviewCard](src/ReviewCard.jsx) is a separate file; [presentation.js](src/presentation.js) maps the API's frozen records to it. The surrounding app and optional example-host panel demonstrate integration.

```bash
npm ci
npm test
npm run build
```

Use Node 22.20+ (or 24.12+). Build output goes into the Python package; Node is unnecessary to run the built demo. The watch command rebuilds assets for the existing local server.

The card accepts `systemId`, `action`, `headline`, `bullets`, ordered `proceedRisks`/`holdRisks`, `recommendation`, `explanation`, permission booleans, availability help, retained evidence and `onDecision`/`onRefresh` callbacks. Each risk has `id`, `priority` and `consequence`. Recommendation text is not a prefilled human rationale. Simple `proceedRisk`/`holdRisk` strings remain available for standalone templates.

The API adapter retains idempotency keys across uncertain mutation retries. The host revision panel also retains its exact request body. New submissions and changed guideline versions require explicit evaluation and decision steps. See [integration](../docs/integration.md) for the API boundaries and [guidelines](../docs/guidelines.md) for editor behavior.
