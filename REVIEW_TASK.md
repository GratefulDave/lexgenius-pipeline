# LexGenius Pipeline — PR Fix Verification & Re-Review

## Context
4 open PRs on GratefulDave/lexgenius-pipeline. Fix branches have been pushed for all. You need to verify fixes and re-review.

## PR Status
- **PR #3** (Judicial Connectors) — Already APPROVED. Merge it.
- **PR #1** (State AG Connectors) — Fixes just pushed. Verify tests pass.
- **PR #2** (Federal Agency Connectors) — Fixes just pushed. Verify tests pass.
- **PR #4** (Commercial/Social Connectors) — Fixes were pushed earlier. Re-review against latest commit.

## Step 1: Merge PR #3
PR #3 is already approved. Merge it:
```bash
gh pr merge 3 --merge
```

## Step 2: Verify PR #1 fixes
```bash
git checkout fix/pr-1-review
git pull origin feature/ag-actions-connectors
pip install -e ".[dev,test]" 2>/dev/null || pip install -e . pytest respx 2>/dev/null
pytest tests/ -x -q --tb=short 2>&1 | tail -30
```
The fixes should address: XXE vulnerability (defusedxml), dead code removal, 5xx error handling, CA TypeError, parser deduplication, date fallback logging, NY title capture, HTTP test mocking.

## Step 3: Verify PR #2 fixes
```bash
git checkout fix/pr-2-review
git pull origin feature/federal-connectors
pytest tests/ -x -q --tb=short 2>&1 | tail -30
```
The fixes should address: EPA ECHO dead code, fingerprint stability, shared parse_date, LinkExtractorParser extraction, module-level imports, HTTP test mocking, unused imports.

## Step 4: Re-review PR #4
Check out the PR #4 branch, read the files that had issues, verify each fix from the original review:
- CRITICAL: JDSupraMassTortConnector httpx resource leak
- HIGH: Reddit OAuth2 env var fallbacks
- HIGH: Reddit 401 retry logic
- HIGH: Regex HTML parsing replaced with BeautifulSoup
- MEDIUM: pytrends made optional
- MEDIUM: Google Trends sync calls wrapped in run_in_executor
- MEDIUM: date fallback logging
- MEDIUM: dead feedparser dependency removed

```bash
git checkout fix/pr-4-review
git pull origin feature/commercial-connectors
# Check the specific files mentioned in the review
```

## Step 5: Report
For each PR, report:
- Tests pass? (yes/no + summary)
- All review issues addressed?
- Any remaining concerns?
- Recommend merge / request changes / needs more work?

If all looks good, merge PRs #1 and #2 as well:
```bash
gh pr merge 1 --merge
gh pr merge 2 --merge
gh pr merge 4 --merge
```

Only merge if tests pass and review issues are addressed.
