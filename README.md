# Football Data Pipeline

A Python ETL project that extracts Premier League match data, validates it, loads it into SQL, and produces a league-table CSV. Built as a personal portfolio project with AI assistance.

**Recorded example:** [`examples/run.json`](examples/run.json) records a local SQLite run with 380 completed 2024/25 Premier League matches and 20 teams. Duplicate-free reruns are covered by SQLite and PostgreSQL tests. A verified GitHub Actions run also loaded 380 matches and produced standings for 20 teams; see [CI evidence](#verified-ci-evidence).

## What it does

1. Downloads OpenFootball's public JSON feed over HTTPS, with timeouts and retries.
2. Saves the original response using its SHA-256 checksum for traceability and replay.
3. Validates dates, team names, fixture identities, and full-time scores before writing to SQL.
4. Upserts matches inside a transaction, updating score or date corrections without duplicating fixtures.
5. Computes standings in SQL and exports `standings.csv` plus a `run.json` manifest.

Supports **PostgreSQL** through Psycopg and **SQLite** for a dependency-free local demo. The GitHub Actions workflow is configured for automated tests, ingestion from the public JSON source, daily scheduling, a temporary PostgreSQL service, and output artifact uploads. Successful execution is documented below for a specific commit and run.

## Run in one command

Python 3.10+ required. Run from this repository's root:

```bash
python -m football_pipeline.pipeline
```

No package installation or API key is needed for the SQLite demo. On Windows, use `py` instead of `python` if necessary.

Outputs (ignored by Git):

- `data/raw/<sha256>.json`: original source snapshot.
- `data/football.db`: SQLite match database.
- `data/standings.csv`: team-level match and goal statistics.
- `data/run.json`: timestamp, source checksum, backend, and row counts.

Run the command twice and compare `stored_matches` in `run.json`: it should remain 380 for the default source.

## PostgreSQL setup

With Docker installed:

```bash
docker compose up -d --wait
python -m pip install -r requirements.txt
```

Set the connection string, then run the same pipeline:

**PowerShell**

```powershell
$env:DATABASE_URL = "postgresql://football:local_demo_only@localhost:5432/football"
python -m football_pipeline.pipeline
```

**Bash**

```bash
export DATABASE_URL='postgresql://football:local_demo_only@localhost:5432/football'
python -m football_pipeline.pipeline
```

The Compose password is for a local demo only; its port is bound to localhost. Never use it for a public database. A named Docker volume preserves local PostgreSQL data. `docker compose down` stops the database without deleting that volume. Remove `DATABASE_URL` from your environment to return to SQLite mode.

## Tests

```bash
python -m unittest discover -s tests -v
```

Five tests run without dependencies. The sixth is a PostgreSQL integration test, enabled by `TEST_DATABASE_URL` pointing to a **dedicated test database**:

```bash
TEST_DATABASE_URL='postgresql://football:local_demo_only@localhost:5432/football' python -m unittest discover -s tests -v
```

Tests cover duplicate-free reruns, corrected scores and dates, invalid inputs, exclusion of unplayed games from standings, transaction rollback, and end-to-end output. The integration test writes a small `Test League 2024/25` dataset and leaves it in the database.

## Replay and configure

```bash
python -m football_pipeline.pipeline --input path/to/snapshot.json
python -m football_pipeline.pipeline --source-url https://raw.githubusercontent.com/openfootball/football.json/master/2023-24/en.1.json
python -m football_pipeline.pipeline --output-dir results --sqlite-path results/football.db
```

The source must follow OpenFootball's `name` and `matches` schema. The competition name includes the season, keeping seasons separate. Only the selected competition appears in each standings export.

## Scheduling and CI

[`.github/workflows/pipeline.yml`](.github/workflows/pipeline.yml) is configured to trigger on pushes, pull requests, manual dispatch, and a daily schedule at 10:17 UTC. GitHub must have Actions enabled; scheduled runs use the default branch and may be delayed by GitHub.

The job is configured to create a **temporary PostgreSQL 16 database**, run the test suite, ingest the source, and upload `data/` as the `football-pipeline-results` artifact with seven-day retention. The upload step runs only if the preceding steps succeed. In PostgreSQL mode, `data/` contains the raw JSON snapshot, standings CSV, and run manifest; it does not contain a PostgreSQL database backup. The service database is discarded after the job, so scheduled runs do not maintain a persistent warehouse.

Persistent operation would require a separately provisioned database, secure connection configuration, and operational controls beyond this demo. The current workflow uses a job-local service connection, not a deployed production database. Never commit a real connection string.

The default season is historical so the demo is reproducible; daily runs do not imply new daily matches. Use another compatible source URL to ingest another season.

### Verified CI evidence

Verified on **2026-10-04** against commit [`aee8cf8ed3decd186aa8646ede02a80163069127`](https://github.com/eocvjr/data-pipeline/commit/aee8cf8ed3decd186aa8646ede02a80163069127):

- GitHub reports scheduled [run #6, ID `37212612163`](https://github.com/eocvjr/data-pipeline/actions/runs/37212612163) as `completed` with conclusion `success`.
- The [job logs](https://github.com/eocvjr/data-pipeline/actions/runs/37212612163/job/111466672080) show all six tests passing, including `test_postgres_rerun`, followed by ingestion of 380 records and output for 20 teams.
- The artifact upload step succeeded, and GitHub's artifact listing confirmed `football-pipeline-results` for that run, with expiry on 2026-10-11. Availability is limited by retention; artifact contents were not independently inspected during this documentation review.

An earlier commit-run lookup returned no results because it was restricted to pull-request-triggered runs. A subsequent repository Actions API query filtered by the same commit SHA, without an event filter, returned runs and enabled the verification above. An empty filtered query does not establish that CI never ran.

This evidence confirms the cited run only. It does not establish that every trigger has been exercised, that future runs will pass, or that the project operates as a production service. The configured schedule time is not a guaranteed start time: the cited run started at 15:20 UTC.

## Design choices and limitations

- Fixture identity hashes competition, round, home team, and away team. Date changes update the existing fixture. Team or round renames change identity; handling these needs stable upstream IDs.
- Validation rejects the entire batch before loading if any record is invalid. Failed raw snapshots remain available for diagnosis.
- SQL writes are transactional. Export files are written after commit; if export fails, rerunning safely regenerates them. `run.json` records the last successful export, so check its timestamp after a failed run.
- Loads are upserts, not deletions. A fixture removed upstream remains in the database; production reconciliation is future work.
- Standings use points, goal difference, and goals scored. Official sanctions and all competition-specific tie-breakers are outside this project.
- This feed is static JSON served over HTTP, not a live sports API. There is no ML model, Airflow deployment, or real-time streaming component.
- The repository includes recorded SQLite output. The cited GitHub Actions run verifies the six-test suite and source ingestion with temporary PostgreSQL. These results do not demonstrate a permanent PostgreSQL warehouse, production reliability, or persistent incremental ingestion across CI jobs.

## Data and references

Data: [OpenFootball football.json](https://github.com/openfootball/football.json), published as public-domain football data. Example source: [2024/25 English Premier League](https://github.com/openfootball/football.json/blob/master/2024-25/en.1.json).

Implementation references: [Psycopg usage](https://www.psycopg.org/psycopg3/docs/basic/usage.html) and [GitHub PostgreSQL service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

## Explain it in an interview

“I built an ETL project that retrieves football match JSON, validates it, loads SQL records, and derives team statistics. I used deterministic fixture keys and transactional upserts so retries and score corrections do not duplicate matches when fixture identity is unchanged. I added tests for failure cases and repeat runs, and integrated GitHub Actions with temporary PostgreSQL, scheduled ingestion, and output artifacts. A linked scheduled run verifies six passing tests and ingestion of 380 matches. I used AI assistance and can explain the implementation and its limitations.”

Walk through `extract`, `validate`, `load`, and `run` in [`football_pipeline/pipeline.py`](football_pipeline/pipeline.py), then inspect the correction and rollback tests. Describe CI results using the linked commit and run evidence. The project is a portfolio ETL demonstration; it does not establish a hosted production warehouse or production operation.
