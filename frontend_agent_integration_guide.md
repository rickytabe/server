# Frontend Integration Guide for Sentinel Gov

## Objective

Replace all dummy data in the frontend with live data from the local backend API running at:

- Base URL: http://127.0.0.1:8000

The frontend must treat the backend as the single source of truth for:
- upload and processing
- analysis progress
- results and risk findings
- on-demand AI-generated report text

---

## Core Rule

Do not use hardcoded sample cards, mock tables, placeholder charts, or fabricated dashboard values.

The frontend must:
1. call the backend API
2. render loading states while waiting
3. show real data once the backend returns results
4. show clear errors if the backend fails

---

## Backend Endpoints You Must Use

The current backend exposes these endpoints:

| Method | Endpoint | Purpose |
|---|---|---|
| GET | / | Health check |
| POST | /api/upload | Upload registry and payroll CSV files |
| GET | /api/status/{job_id} | Poll analysis status |
| GET | /api/results/{job_id} | Fetch completed analysis results |
| POST | /api/ai-summary/{job_id}?language={currentLanguage} | Generate or fetch cached localized AI report |

### Important note
The current backend does not implement PUT or DELETE endpoints. For this project, the frontend should only use GET and POST for the MVP.

---

## Recommended Frontend Flow

### 1. Health check
Before doing anything else, the frontend should verify that the backend is reachable.

Use:
- GET http://127.0.0.1:8000/

Expected response:
```json
{
  "message": "Sentinel Gov Backend API is running."
}
```

If this fails, show a connection error and instruct the user to start the backend.

---

### 2. Upload files
The frontend should collect:
- registry CSV
- payroll CSV
- optional salary rules CSV

Then send a multipart POST request to:
- POST http://127.0.0.1:8000/api/upload

#### Required form fields
- registry_file
- payroll_file
- salary_rules_file (optional)

#### Required CSV columns

Registry CSV must include:
```text
matricule, full_name, national_id, phone, ministry, department, grade, duty_post_code, category, class_echelon, hire_date, location
```

Payroll CSV must include:
```text
matricule, employee_name, base_salary, allowance_codes, total_salary, bank_name, bank_account, payment_date
```

Optional salary rules CSV must include:
```text
grade, duty_post_code, class_echelon, expected_salary
```

The frontend should validate all required headers before upload, not just `matricule` or other primary identifiers. Header matching should trim whitespace and compare case-insensitively.

#### Example request
```ts
const formData = new FormData();
formData.append('registry_file', registryFile);
formData.append('payroll_file', payrollFile);
if (salaryRulesFile) {
  formData.append('salary_rules_file', salaryRulesFile);
}

const response = await fetch('http://127.0.0.1:8000/api/upload', {
  method: 'POST',
  body: formData,
});

const data = await response.json();
```

#### Expected response
```json
{
  "job_id": "uuid-string",
  "message": "Processing started",
  "salary_rules_received": true
}
```

Store the returned job_id in frontend state.

If upload validation fails, the backend returns HTTP 400 and does not create a job:

```json
{
  "detail": {
    "message": "CSV schema validation failed.",
    "errors": [
      {
        "file": "registry_file",
        "missing_columns": ["category", "class_echelon"],
        "required_columns": ["matricule", "full_name"],
        "received_columns": ["matricule", "full_name"]
      }
    ]
  }
}
```

Show these missing columns directly in the upload UI.

---

### 3. Poll processing status
After upload, the frontend must poll the backend until the job reaches a terminal state.

Use:
- GET http://127.0.0.1:8000/api/status/{job_id}

#### Expected status values
The backend uses these statuses:
- pending
- processing
- completed
- failed

#### Example polling logic
```ts
async function pollJobStatus(jobId: string) {
  const response = await fetch(`http://127.0.0.1:8000/api/status/${jobId}`);
  const data = await response.json();
  return data;
}
```

The frontend should show:
- a spinner or progress indicator while status is pending or processing
- the current backend `step` if present, such as `fuzzy_name_matching` or `fraud_network_construction`
- a failure message if status becomes failed
- the backend `error_type` and `error` fields if status becomes failed
- the results screen only after completed

---

### 4. Fetch final results
Once the status is completed, call:
- GET http://127.0.0.1:8000/api/results/{job_id}

#### Expected result structure
The backend returns a large results object containing:
- message
- stats
- source_data
- exact_match_findings
- fuzzy_name_findings
- ghost_workers
- salary_anomaly_findings
- fraud_network_findings
- risk_score_findings
- ai_summary

The frontend should use the returned data to populate the dashboard.

Important:
- `source_data.registry_records` contains the complete registry rows, including `hire_date`.
- `source_data.payroll_records` contains the complete payroll rows, including `payment_date`.
- `GET /api/results/{job_id}` does not return AI report text.
- The AI report is generated only when the frontend calls `POST /api/ai-summary/{job_id}?language={currentLanguage}`.

---

## What the Frontend Should Display

The dashboard should be driven by the backend response, not by dummy data.

### A. Summary cards
Use the backend stats object to populate:
- total registry records
- total payroll records
- duplicate counts
- ghost worker count
- fraud network count
- employees with risk
- highest risk score

### B. Risk overview
Use the risk score summary to display:
- risk distribution by level
- number of employees with risk
- highest risk score

### C. Findings sections
Render sections based on backend results:
- duplicate national IDs
- duplicate bank accounts
- duplicate matricules
- fuzzy name matches
- ghost workers
- salary anomalies
- fraud networks

### D. Employee risk table
Use the risk_score_findings.records array to build a table showing:
- matricule
- full name or employee name
- risk score
- risk level
- risk factors

### E. AI report panel
Show a Generate Report button. When clicked, call:
- POST http://127.0.0.1:8000/api/ai-summary/{job_id}?language={currentLanguage}

The frontend is bilingual. Pass the current UI language to the backend as `language`.
Supported report languages:
- `en`
- `fr`

The backend generates and caches AI reports separately per language, so English and French reports do not overwrite each other.

Render the returned `ai_report.text` content as the narrative report.
Use the frontend i18n system for UI labels, buttons, loading states, and errors. Do not translate `ai_report.text` on the client; render it exactly as returned by the backend.

---

## Data Mapping Guide

The frontend agent should map backend response fields like this:

### Summary metrics
Use:
- stats.total_registry_records
- stats.total_payroll_records
- stats.duplicate_national_ids_found
- stats.duplicate_bank_accounts_found
- stats.potential_ghost_workers
- stats.fraud_networks_found
- stats.employees_with_risk
- stats.highest_risk_score

### Duplicate findings
Use:
- exact_match_findings.registry_duplicate_national_ids
- exact_match_findings.registry_duplicate_matricules
- exact_match_findings.payroll_duplicate_bank_accounts
- exact_match_findings.payroll_duplicate_matricules

### Fuzzy name matches
Use:
- fuzzy_name_findings.registry_fuzzy_name_matches.matches
- fuzzy_name_findings.payroll_fuzzy_name_matches.matches

### Ghost workers
Use:
- ghost_workers.records

### Salary anomalies
Use:
- salary_anomaly_findings.rule_based.records
- salary_anomaly_findings.statistical.records

### Fraud networks
Use:
- fraud_network_findings.networks

### Risk scoring
Use:
- risk_score_findings.summary
- risk_score_findings.records

### AI report
Use:
- POST /api/ai-summary/{job_id}?language={currentLanguage}
- ai_report.text from that endpoint response

---

## Frontend State Design

The frontend should maintain state like this:

```ts
type AppState = {
  isConnected: boolean;
  isUploading: boolean;
  jobId: string | null;
  status: 'idle' | 'pending' | 'processing' | 'completed' | 'failed';
  results: any | null;
  currentLanguage: 'en' | 'fr';
  aiReportsByLanguage: Partial<Record<'en' | 'fr', any>>;
  isGeneratingAiReport: boolean;
  error: string | null;
};
```

### Suggested lifecycle
1. Check backend health
2. Upload files
3. Save job_id
4. Poll status
5. When completed, fetch results
6. Render dashboard from results
7. Generate AI report only when the user clicks Generate Report

---

## Error Handling Rules

The frontend must handle these cases clearly:

- backend not running
- upload failed
- invalid CSV schema
- processing failed
- results not ready yet
- job not found

### Show user-friendly messages for:
- "Backend is unavailable"
- "Analysis failed"
- "Please upload valid registry and payroll CSV files"
- "The analysis is still running"

---

## CORS Note

If the frontend runs from a different origin such as a Next.js dev app on port 3000, the backend must allow cross-origin requests.

The current backend already allows requests from:
- http://localhost:3000
- http://127.0.0.1:3000

---

## Start the Backend Locally

Before testing the frontend, the backend should be started with:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Then test the health endpoint:

```bash
curl http://127.0.0.1:8000/
```

---

## Do Not Do These Things

The frontend agent should not:
- invent mock dashboard cards
- hardcode suspicious employee examples
- create fake charts from static arrays
- assume the backend is already done without calling it
- use placeholder data for the report section

The frontend should be fully driven by the backend responses.

---

## Acceptance Criteria

The integration is complete when:
1. the frontend can upload files to the backend
2. the frontend can poll job status from the backend
3. the frontend can fetch and render the final results
4. no dummy data is required for the dashboard
5. the UI reflects real backend findings
6. loading and error states work correctly

---

## Recommended Implementation Order

1. Replace all static mock data with API state
2. Add upload form and file submission
3. Add job polling and status UI
4. Render summary cards from backend stats
5. Render findings sections from backend results
6. Render employee risk table from risk_score_findings.records
7. Add Generate Report button that calls POST /api/ai-summary/{job_id}?language={currentLanguage}
8. Render AI report from ai_report.text returned by the AI summary endpoint
9. Add error and retry handling

---

## Current Frontend Route Structure

Use the existing route structure. Do not invent a separate `/dashboard/fraud-networks` route.

The app routes are:
- `/` - landing/home page
- `/dashboard` - main dashboard view
- `/upload` - upload payroll/employee files for a new scan
- `/scans/[id]` - a specific scan context
- `/scans/[id]/overview` - scan overview
- `/scans/[id]/processing` - live processing status
- `/scans/[id]/results` - list of flagged employees
- `/scans/[id]/employees/[employeeId]` - employee investigation detail page
- `/scans/[id]/fraud-network` - fraud network investigation graph
- `/scans/[id]/report` - audit report summary

Treat `[id]` as the backend `job_id` returned by `POST /api/upload`.

Route behavior:
- `/upload` starts a new backend scan and redirects to `/scans/[id]/processing`.
- `/scans/[id]/processing` polls `GET /api/status/{job_id}` until complete.
- `/scans/[id]/overview`, `/scans/[id]/results`, `/scans/[id]/fraud-network`, and `/scans/[id]/report` all read from `GET /api/results/{job_id}`.
- `/scans/[id]/report` calls `POST /api/ai-summary/{job_id}?language={currentLanguage}` only when the user clicks Generate Report.
- `/scans/[id]/fraud-network` uses `fraud_network_findings.networks` and `risk_score_findings.records`.

---

## Fraud Network Master Prompt

Keep the detailed frontend prompt for `/scans/[id]/fraud-network` outside this integration guide. This guide should explain API integration; the master prompt should describe the visual and interaction design for that route.

---

## Final Instruction to the Frontend Agent

Build the frontend around the backend API, not around dummy data.

Use:
- POST /api/upload for analysis start
- GET /api/status/{job_id} for progress
- GET /api/results/{job_id} for final dashboard data
- POST /api/ai-summary/{job_id}?language={currentLanguage} for on-demand AI report generation

Treat http://127.0.0.1:8000 as the live backend endpoint for the full MVP experience.
