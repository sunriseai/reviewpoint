# Development and local operations

## Install and verify

Python 3.12 and 3.13 are supported on macOS/Linux; the local workspace lock uses POSIX file locking. Frontend development uses Node 22.20+ (or 24.12+) and npm. Dependency resolution is locked; install dependencies once before offline checks.

```bash
uv sync --locked --extra openai
npm ci --prefix frontend
uv run --frozen --offline pytest -q
uv run --frozen --offline ruff check src tests tools examples
uv run --frozen --offline ruff format --check src tests tools examples
uv run --frozen --offline mypy src/reviewpoint
uv run --frozen --offline reviewpoint export-contracts --check
uv run --frozen --offline python tools/check_docs.py
uv run --frozen --offline python tools/check_release.py
npm run format:check --prefix frontend
npm run test --prefix frontend
npm run build --prefix frontend
```

Tests disable outbound network access and remove the provider key. Optional provider behavior uses explicit stubs. Test-only projects exercise isolation and the other check methods; the interactive demo has one example.

Vite builds the complete React app into the packaged assets. Keep generated assets with frontend changes. `npm run dev --prefix frontend` watches and rebuilds; refresh the service page to load changes. CI compares generated assets and contracts for drift. No CDN is needed at runtime, including `/docs`: the build includes Swagger UI assets, a same-origin initializer and upstream license notices. Documentation permits inline style attributes and embedded images only on `/docs`; application pages retain the stricter policy.

## Tested offline walkthrough

This command block is executed by a documentation test from a standalone working directory. It prepares WORK-001 without making a human decision, resumes it, verifies storage and creates a backup.

<!-- offline-quickstart:start -->
```bash
reviewpoint demo --prepare-only --workspace .workspace
reviewpoint demo --prepare-only --workspace .workspace
reviewpoint verify --workspace .workspace
reviewpoint backup backup.sqlite3 --workspace .workspace
```
<!-- offline-quickstart:end -->

For ordinary development, `reviewpoint init` creates a fresh local workspace, `reviewpoint serve` starts the core service, and `reviewpoint demo` additionally prepares the single example and installs the example-host routes. Both servers default to loopback port 8767. Existing workspaces are never reset automatically.

## Storage and operations

Use one process per workspace. `reviewpoint.sqlite3` uses foreign keys, WAL and transactional writes. The process lock prevents a second evaluator server from recovering an active worker's attempts. Queue admission is bounded; model calls happen outside database write transactions. Startup marks interrupted attempts failed; users explicitly request a new evaluation. Failure never becomes approval.

`reviewpoint verify` checks database integrity and record hashes. This detects ordinary corruption, not administrator replacement or unsound judgment. `reviewpoint backup /new/path.sqlite3` uses SQLite's backup API and refuses an existing destination. To restore, stop the service and test a backup copy in a separate workspace with the appropriate private configuration before replacing working data.

Keep `config.json` and `demo-credentials.json` private. Databases and backups contain submitted evidence, decisions and interpretation records; they are not public examples. `.gitignore` excludes local workspaces, credentials through the workspace directory, build environments and database files. The release check also detects accidental artifacts outside those locations. No retention automation or deletion API is provided.

Ordinary errors expose bounded messages and request IDs, without raw provider errors or keys. Evidence is rendered as text. No source URL is fetched. Access logs are disabled by the launcher.

## Optional OpenAI interpretation

1. Install the optional adapter with `uv sync --locked --extra openai`.
2. Set `OPENAI_API_KEY` in the server environment. Never put it in the UI, submitted work or committed files.
3. Set `model` in the private workspace `config.json` to a model available to your account that supports Responses API structured outputs and the adapter's reasoning settings. There is no assumed cheapest model or automatic fallback.
4. Start `reviewpoint demo --live` or `reviewpoint serve --live`.
5. Publish a profile containing a `semantic_review` requirement through the API, then explicitly request its evaluation.

Each semantic call sends the **complete retained work, context and evidence**, submission summary and work type, proposed action, named requirement, and relevant guideline scope and risks to OpenAI. This is the full retained input, not just the citations returned by the model. The local database and its backups retain the request and validated or rejected output; public assessment responses expose filtered run metadata. `store=false` is a request setting, not an independent guarantee about provider retention.

The guided editor preserves semantic requirements as API-managed; it does not author them. Each semantic check can incur a paid request. There are no automatic paid retries or model escalation. Invalid citations, refusals and incomplete output fail the assessment. The API's stored run metadata and limits describe the attempt, not an independent guarantee of model correctness or provider retention.

## Before public release

Run all checks, build a wheel and test an isolated copy of the repository. CI installs the wheel into a fresh environment with locked runtime dependencies and runs `tools/check_installed.py` with only that environment on PATH, so Node is unavailable. The check verifies offline preparation/resume, integrity, backup, authenticated API access, and packaged application/documentation assets.

For a manual browser check, block external requests, open `/docs`, authorize and execute a local GET, then reload and confirm credentials are cleared and no CSP errors occurred.

Review the release-content report and the actual file list; a scanner is not proof that arbitrary secrets or private prose are absent. The repository contains no remote configuration or package-publishing credentials. Name/package availability and shared production deployment remain separate decisions.
