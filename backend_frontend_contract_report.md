# Backend Frontend Contract Report

This report describes the current backend behavior implemented in [main.py](main.py) and the payload shape seen in [response_data.json](response_data.json).

## 1. What the backend currently does

The backend is a payroll fraud-analysis pipeline with these capabilities:

1. File ingestion
   - Reads registry CSV and payroll CSV files
   - Normalizes column names and trims whitespace
   - Uppercases employee names for matching

2. Schema validation
   - Verifies required columns for registry CSV
   - Verifies required columns for payroll CSV
   - Verifies required columns for optional salary rules CSV

3. Duplicate detection
   - Detects duplicate national IDs
   - Detects duplicate matricules in registry
   - Detects duplicate bank accounts in payroll
   - Detects duplicate matricules in payroll

4. Fuzzy name matching
   - Compares employee names using blocked fuzzy matching
   - Uses first/last-name initials as buckets
   - Flags names above the 85% similarity threshold

5. Ghost worker detection
   - Finds payroll matricules that do not exist in the registry

6. Salary anomaly detection
   - Rule-based checks against salary rules CSV if supplied
   - Statistical checks using Isolation Forest when enough salary records exist

7. Fraud network analysis
   - Builds a graph of employees
   - Adds edges for shared bank accounts, shared national IDs, and fuzzy-name links
   - Computes connected components as suspicious networks

8. Risk scoring
   - Assigns risk points for duplicate IDs, shared bank accounts, ghost workers, salary anomalies, and network membership
   - Maps raw score to Low / Moderate / High / Critical

9. On-demand AI report generation
   - Generates a human-readable report only when the frontend calls the AI summary endpoint
   - Sends only summarized/anonymized findings to the AI engine
   - Uses Gemini when an API key is available
   - Falls back to a deterministic local report when not available
   - Caches the generated report for the job

10. Async job processing
   - Uploads files and returns a job ID
   - Polls job status until completed
   - Returns final analysis results once finished without automatically generating the AI report

---

## 2. Backend API surface

### Health check

Endpoint:
- GET /

Response shape:
```json
{
  "message": "Sentinel Gov Backend API is running."
}
```

### Upload files

Endpoint:
- POST /api/upload

Expected multipart fields:
- registry_file: file
- payroll_file: file
- salary_rules_file: optional file

Response shape:
```json
{
  "job_id": "string",
  "message": "Processing started",
  "salary_rules_received": true
}
```

Validation error response:
```json
{
  "detail": {
    "message": "CSV schema validation failed.",
    "errors": [
      {
        "file": "registry_file",
        "missing_columns": ["category", "class_echelon", "duty_post_code"],
        "required_columns": ["matricule", "full_name"],
        "received_columns": ["matricule", "full_name"]
      }
    ]
  }
}
```

Important:
- Upload schema validation happens before the background job starts.
- If this validation fails, the frontend will not receive a `job_id`.
- Validate the CSV headers in the frontend before upload using the required columns listed in this contract.

### Check job status

Endpoint:
- GET /api/status/{job_id}

Response shape:
```json
{
  "job_id": "string",
  "status": "pending | processing | completed | failed",
  "ai_summary_status": "not_ready | not_requested | generating | completed | failed",
  "ai_summary_status_by_language": {
    "en": "not_requested | generating | completed | failed",
    "fr": "not_requested | generating | completed | failed"
  },
  "step": "queued | data_ingestion | exact_match_detection | fuzzy_name_matching | ghost_worker_detection | salary_anomaly_detection | fraud_network_construction | risk_scoring | building_response | completed",
  "error_type": "string, only present when failed",
  "error": "string, only present when failed"
}
```

### Fetch analysis results

Endpoint:
- GET /api/results/{job_id}

Response shape:
```json
{
  "message": "Analysis completed",
  "stats": { },
  "source_data": {
    "registry_columns": ["matricule", "full_name", "national_id", "phone", "ministry", "department", "grade", "duty_post_code", "category", "class_echelon", "hire_date", "location"],
    "payroll_columns": ["matricule", "employee_name", "base_salary", "allowance_codes", "total_salary", "bank_name", "bank_account", "payment_date"],
    "registry_records": [],
    "payroll_records": []
  },
  "exact_match_findings": { },
  "fuzzy_name_findings": { },
  "ghost_workers": { },
  "salary_anomaly_findings": { },
  "fraud_network_findings": { },
  "risk_score_findings": { },
  "ai_summary": {
    "status": "not_requested | completed",
    "generate_endpoint": "/api/ai-summary/{job_id}",
    "default_language": "en",
    "supported_languages": ["en", "fr"],
    "generated_languages": [],
    "status_by_language": {
      "en": "not_requested",
      "fr": "not_requested"
    }
  }
}
```

Important:
- This endpoint does not call Gemini.
- This endpoint does not return the generated AI report text.
- The frontend should call the AI summary endpoint when the user clicks Generate Report.
- Complete uploaded registry/payroll rows are available under `source_data.registry_records` and `source_data.payroll_records`.

### Generate AI summary

Endpoint:
- POST /api/ai-summary/{job_id}

Optional query parameter:
- force: boolean, defaults to false
- language: string, defaults to `en`; supported values are `en` and `fr`

Examples:
- `POST /api/ai-summary/{job_id}?language=en`
- `POST /api/ai-summary/{job_id}?language=fr`
- `POST /api/ai-summary/{job_id}?language=fr&force=true`

Response shape:
```json
{
  "job_id": "string",
  "cached": false,
  "language": "fr",
  "ai_summary_status": "completed",
  "supported_languages": ["en", "fr"],
  "ai_report": {
    "enabled": true,
    "provider": "gemini",
    "model": "gemini-2.5-flash",
    "language": "fr",
    "text": "string"
  }
}
```

If `cached` is true, the backend returned a previously generated report for the requested language and did not call Gemini again.

Use `POST /api/ai-summary/{job_id}?language={language}&force=true` only when the user intentionally wants to regenerate that language's report.

### Common error response

For job lookup and incomplete-job errors, the backend currently uses FastAPI `HTTPException`, so the frontend should expect this shape:

```json
{
  "detail": "Job not found"
}
```

Common statuses:
- 404: job ID does not exist
- 400: job is not completed yet
- 400: unsupported AI report language
- 500: AI summary generation failed unexpectedly

---

## 3. JSON types used by the backend

The backend is written in Python, but the API responses are JSON. The following is the practical frontend-facing contract.

### Primitive types

- string
- number
- boolean
- null
- array
- object

### Important backend note

Some fields are returned as strings even when they conceptually represent numbers, especially salary-like values and IDs. The backend uses pandas and string-based CSV parsing, so frontend code should not assume every numeric-looking field is a number.

---

## 4. Main response objects

### Shared status types

```ts
type JobStatus = "pending" | "processing" | "completed" | "failed";
type AiSummaryStatus =
  | "not_ready"
  | "not_requested"
  | "generating"
  | "completed"
  | "failed";
```

### UploadResponse

```ts
interface UploadResponse {
  job_id: string;
  message: string;
  salary_rules_received: boolean;
}
```

```ts
interface UploadValidationErrorResponse {
  detail: {
    message: "CSV schema validation failed.";
    errors: CsvSchemaValidationError[];
  };
}
```

```ts
interface CsvSchemaValidationError {
  file: "registry_file" | "payroll_file" | "salary_rules_file";
  missing_columns: string[];
  required_columns: string[];
  received_columns: string[];
}
```

### JobStatusResponse

```ts
interface JobStatusResponse {
  job_id: string;
  status: JobStatus;
  ai_summary_status: AiSummaryStatus;
  ai_summary_status_by_language: Partial<Record<"en" | "fr", AiSummaryStatus>>;
  step?: string;
  error_type?: string;
  error?: string;
}
```

### AnalysisResults

```ts
interface AnalysisResults {
  message: string;
  stats: Stats;
  source_data: SourceData;
  exact_match_findings: ExactMatchFindings;
  fuzzy_name_findings: FuzzyNameFindings;
  ghost_workers: GhostWorkers;
  salary_anomaly_findings: SalaryAnomalyFindings;
  fraud_network_findings: FraudNetworkFindings;
  risk_score_findings: RiskScoreFindings;
  ai_summary: AiSummaryMarker;
}
```

```ts
interface SourceData {
  registry_columns: RegistryColumn[];
  payroll_columns: PayrollColumn[];
  registry_records: RegistryRecord[];
  payroll_records: PayrollRecord[];
}
```

```ts
type RegistryColumn =
  | "matricule"
  | "full_name"
  | "national_id"
  | "phone"
  | "ministry"
  | "department"
  | "grade"
  | "duty_post_code"
  | "category"
  | "class_echelon"
  | "hire_date"
  | "location";
```

```ts
type PayrollColumn =
  | "matricule"
  | "employee_name"
  | "base_salary"
  | "allowance_codes"
  | "total_salary"
  | "bank_name"
  | "bank_account"
  | "payment_date";
```

```ts
interface RegistryRecord {
  matricule: string;
  full_name: string;
  national_id: string;
  phone: string;
  ministry: string;
  department: string;
  grade: string;
  duty_post_code: string;
  category: string;
  class_echelon: string;
  hire_date: string;
  location: string;
}
```

```ts
interface PayrollRecord {
  matricule: string;
  employee_name: string;
  base_salary: string;
  allowance_codes: string;
  total_salary: string;
  bank_name: string;
  bank_account: string;
  payment_date: string;
}
```

```ts
type EmployeeCombinedRecord = RegistryRecord & Omit<PayrollRecord, "matricule">;
```

```ts
interface AiSummaryMarker {
  status: AiSummaryStatus;
  generate_endpoint: string;
  default_language: "en";
  supported_languages: Array<"en" | "fr">;
  generated_languages: Array<"en" | "fr">;
  status_by_language: Record<"en" | "fr", AiSummaryStatus>;
}
```

---

## 5. Stats object

```ts
interface Stats {
  total_registry_records: number;
  total_payroll_records: number;
  duplicate_national_ids_found: number;
  duplicate_bank_accounts_found: number;
  duplicate_registry_matricules_found: number;
  duplicate_payroll_matricules_found: number;
  registry_fuzzy_name_matches_found: number;
  payroll_fuzzy_name_matches_found: number;
  potential_ghost_workers: number;
  salary_rule_anomalies_found: number;
  salary_statistical_anomalies_found: number;
  fraud_networks_found: number;
  employees_with_risk: number;
  highest_risk_score: number;
}
```

---

## 6. Exact match findings

```ts
interface ExactMatchFindings {
  registry_duplicate_national_ids: DuplicateFinding;
  registry_duplicate_matricules: DuplicateFinding;
  payroll_duplicate_bank_accounts: DuplicateFinding;
  payroll_duplicate_matricules: DuplicateFinding;
}
```

```ts
interface DuplicateFinding {
  duplicate_value_count: number;
  affected_record_count: number;
  duplicate_values: string[];
  records: DuplicateRecord[];
}
```

```ts
type DuplicateRecord = Partial<RegistryRecord & PayrollRecord>;
```

---

## 7. Fuzzy name findings

```ts
interface FuzzyNameFindings {
  registry_fuzzy_name_matches: FuzzyNameFinding;
  payroll_fuzzy_name_matches: FuzzyNameFinding;
}
```

```ts
interface FuzzyNameFinding {
  threshold: number;
  blocking_rule: string;
  record_count: number;
  bucket_count: number;
  unblocked_pair_count: number;
  candidate_pair_count: number;
  match_count: number;
  matches: FuzzyMatch[];
}
```

```ts
interface FuzzyMatch {
  score: number;
  left: Partial<RegistryRecord & PayrollRecord>;
  right: Partial<RegistryRecord & PayrollRecord>;
}
```

---

## 8. Ghost workers

```ts
interface GhostWorkers {
  ghost_worker_count: number;
  matricules: string[];
  records: GhostWorkerRecord[];
}
```

```ts
type GhostWorkerRecord = PayrollRecord;
```

---

## 9. Salary anomaly findings

```ts
interface SalaryAnomalyFindings {
  rule_based: SalaryAnomalyGroup;
  statistical: SalaryAnomalyGroup;
}
```

```ts
interface SalaryAnomalyGroup {
  enabled: boolean;
  reason?: string;
  default_tolerance?: number;
  rules_loaded?: number;
  invalid_rule_count?: number;
  duplicate_rule_count?: number;
  records_checked: number;
  missing_rule_count?: number;
  invalid_salary_count?: number;
  anomaly_count: number;
  records: SalaryAnomalyRecord[];
  method?: string;
  contamination?: number;
}
```

```ts
type SalaryAnomalyRecord = EmployeeCombinedRecord & {
  total_salary: string;
  actual_salary?: number;
  expected_salary?: number;
  tolerance?: number;
  allowed_min?: number;
  allowed_max?: number;
  difference?: number;
  ml_score?: number;
};
```

---

## 10. Fraud network findings

```ts
interface FraudNetworkFindings {
  algorithm: string;
  node_count: number;
  edge_count: number;
  network_count: number;
  edge_sources: {
    shared_bank_account_edges: number;
    shared_national_id_edges: number;
    fuzzy_name_edges: number;
  };
  networks: FraudNetwork[];
}
```

```ts
interface FraudNetwork {
  network_id: number;
  size: number;
  member_matricules: string[];
  members: FraudNetworkMember[];
  reasons: string[];
  edge_count: number;
  edges: FraudNetworkEdge[];
}
```

```ts
type FraudNetworkMember = EmployeeCombinedRecord;
```

```ts
interface FraudNetworkEdge {
  left: string;
  right: string;
  reasons: string[];
  evidence: Array<Record<string, unknown>>;
}
```

---

## 11. Risk score findings

```ts
interface RiskScoreFindings {
  weights: {
    duplicate_id: number;
    shared_bank_account: number;
    ghost_worker: number;
    salary_anomaly: number;
    network_membership: number;
  };
  level_mapping: {
    Low: string;
    Moderate: string;
    High: string;
    Critical: string;
  };
  summary: RiskSummary;
  records: RiskScoreRecord[];
}
```

```ts
interface RiskSummary {
  employee_count: number;
  employees_with_risk: number;
  highest_risk_score: number;
  level_counts: {
    Low: number;
    Moderate: number;
    High: number;
    Critical: number;
  };
}
```

```ts
type RiskScoreRecord = EmployeeCombinedRecord & {
  raw_score: number;
  risk_score: number;
  risk_level: "Low" | "Moderate" | "High" | "Critical";
  risk_factors: RiskFactor[];
};
```

```ts
interface RiskFactor {
  factor: string;
  points: number;
  evidence: Array<Record<string, unknown>>;
}
```

---

## 12. AI summary endpoint response

```ts
interface AiSummaryResponse {
  job_id: string;
  cached: boolean;
  language: "en" | "fr";
  ai_summary_status: AiSummaryStatus;
  supported_languages: Array<"en" | "fr">;
  ai_report: AiReport;
}
```

```ts
interface AiReport {
  enabled: boolean;
  provider: string;
  reason?: string;
  model?: string | null;
  language: "en" | "fr";
  text: string;
}
```

Possible `provider` values currently include:
- `gemini`
- `local_fallback`

Frontend behavior:
- Show the Generate Report button when `AnalysisResults.ai_summary.status` is `not_requested`
- Call `POST /api/ai-summary/{job_id}?language={currentLanguage}` when the user clicks Generate Report
- Store/render `AiSummaryResponse.ai_report.text`
- If `cached` is true, tell the UI nothing special unless you want to show "previously generated"
- Cache the rendered report by language in frontend state if users can switch between English and French

---

## 13. Common frontend mismatch risks

The most likely frontend type mismatches come from these backend realities:

1. Salary values are not always numeric on the wire
   - Some fields are strings, especially in records like `total_salary`, `actual_salary`, or `expected_salary`.

2. Some values may be empty strings
   - Many fields use empty strings instead of null.

3. Risk-level values are strings, not enums
   - The backend returns values such as `Low`, `Moderate`, `High`, and `Critical` as plain strings.

4. Arrays are often optional or empty
   - `records`, `matches`, `risk_factors`, and `edges` can be empty arrays.

5. Analysis results do not include the AI report text
   - `GET /api/results/{job_id}` returns `ai_summary`, not `ai_report`.
   - The frontend must call `POST /api/ai-summary/{job_id}?language={currentLanguage}` to get `ai_report.text`.

6. The backend uses dynamic dictionaries
   - Some sections are objects with keys that are not strictly known at compile time, especially evidence payloads.

7. The API is not strongly typed at the FastAPI layer
   - The backend returns Python dictionaries and lists directly, so the frontend should validate at runtime.

---

## 14. Recommended frontend contract approach

For the frontend, the safest approach is:

- Use the TypeScript interfaces above as the source of truth
- Treat salary-related values as `string | number`
- Treat nullable/empty fields as `string | null`
- Use runtime validation with `zod` or similar if possible
- Avoid assuming all objects are fully populated
- Keep AI report state separate from analysis results state

---

## 15. Practical advice for the current frontend

If the frontend is failing with type mismatches, the fastest fixes are:

1. Make the UI use the backend response interfaces above
2. Normalize salary fields before rendering charts or tables
3. Coerce empty strings to `null` or `""` consistently
4. Use `Array.isArray(...)` guards when mapping nested data
5. Treat `risk_factors` and `evidence` as arrays of objects rather than fixed shapes
6. On the AI Audit page, call `POST /api/ai-summary/{job_id}?language={currentLanguage}` only after the user clicks Generate Report

Recommended frontend flow:

1. Upload files with `POST /api/upload`
2. Poll `GET /api/status/{job_id}` until `status === "completed"`
3. Fetch deterministic results with `GET /api/results/{job_id}`
4. Render dashboard/tables from `AnalysisResults`
5. On the AI Audit page, call `POST /api/ai-summary/{job_id}?language={currentLanguage}` when the user asks for the report
6. Render `AiSummaryResponse.ai_report.text`

---

## 16. Best next step

The best next improvement would be to build a small frontend API client around this contract, with separate functions for upload, status polling, results fetching, and AI summary generation.
