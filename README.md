# ETL Validator

A data quality platform for validating ETL pipelines. Compare source and target datasets across databases or CSV files with configurable checks, then view results in a modern web UI or generate reports for CI/CD.

## Features

- **6 validation checks**: Row Count, Schema, Nulls, Duplicates, Data Diff (hash/full/sample), Aggregates
- **Multiple modes**: Web UI, CLI, YAML-driven suites
- **CSV & database support**: Upload CSV files or connect to Teradata via ODBC
- **Batch execution**: Validate multiple query pairs in one run (import from Excel/CSV)
- **Auto-profiler**: Connect to a table, profile all columns, auto-generate a test suite
- **Reports**: Excel, standalone HTML, JUnit XML
- **History**: SQLite-backed result store with trending

## Tech Stack

| Layer | Stack |
|-------|-------|
| Backend | Python, FastAPI, pandas, DuckDB |
| Frontend | React 19, Vite, MUI v9, Recharts |
| Connectors | Teradata (pyodbc), CSV (pandas) |
| Reports | Excel (xlsxwriter), HTML, JUnit XML |

## Quick Start

### Backend

```bash
pip install -r requirements.txt

# Start API server
python -m uvicorn etl_validator.api:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### CLI

```bash
pip install -e .

# Run a test suite
etl-validate run tests/suite.yaml

# Run with parallel execution
etl-validate run tests/suite.yaml --parallel --workers 8

# Auto-profile a table and generate a suite
etl-validate profile --table DB.SCHEMA.TABLE --dsn "$DSN" --output suite.yaml
```

## Project Structure

```
etl_validator/
├── api.py              # FastAPI REST API
├── cli.py              # CLI (Click)
├── checks/             # Validation checks (row_count, metadata, null, duplicate, data, aggregate)
├── connectors/         # DB connectors (Teradata, CSV)
├── engine/             # Executor, suite loader, result store, profiler, resilience
├── reports/            # Excel, HTML, JUnit XML formatters
├── frontend/           # React SPA
│   └── src/
│       ├── pages/      # Dashboard, AdhocTest, SuiteRunner, Connections, Results
│       └── components/ # Shared UI components
├── requirements.txt
└── pyproject.toml
```

## Validation Checks

| Check | Description |
|-------|-------------|
| Row Count | Source vs target row count with configurable tolerance |
| Schema | Column names, data types, nullability comparison |
| Null Check | Null counts per column across source and target |
| Duplicate | Detect duplicate records unique to each side |
| Data Diff | Row-level comparison — hash, full diff, or sample strategies |
| Aggregate | MIN/MAX/AVG/SUM per column comparison |

##Kill & restart backend:
```# Kill anything on port 8000
netstat -ano | findstr :8000
taskkill /PID <PID_FROM_ABOVE> /F

# Or one-liner to kill all on port 8000:
for /f "tokens=5" %a in ('netstat -ano ^| findstr :8000') do taskkill /PID %a /F

# Start backend
cd C:\path\to\etl_validator
pip install -e .
python -m uvicorn etl_validator.api:app --reload --port 8000 --host 0.0.0.0
```

##Kill & restart frontend:
```# Kill anything on port 5176
for /f "tokens=5" %a in ('netstat -ano ^| findstr :5176') do taskkill /PID %a /F

# Start frontend
cd C:\path\to\etl_validator\frontend
npm install
npm run dev -- --port 5176 --host 0.0.0.0
```




