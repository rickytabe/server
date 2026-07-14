# Sentinel Gov: Backend Implementation Plan

## Overview
This document outlines the detailed implementation plan for the backend of Sentinel Gov, based on the *Updated MVP Roadmap (SIN 2026 Edition)*. The focus is on a fast, deterministic, and fully local architecture that proves technical feasibility for the MVP.

## Tech Stack
*   **Framework:** FastAPI (Python) - for asynchronous processing and data/ML library compatibility.
*   **Data Processing:** Pandas - for instant vectorized operations on 14k+ rows.
*   **Fuzzy Matching:** RapidFuzz - fast string matching.
*   **Graph Analysis:** NetworkX - for fraud network discovery using connected components.
*   **Machine Learning (Anomaly Detection):** scikit-learn (Isolation Forest).
*   **AI API:** Gemini API - exclusively for final report generation (due to hardware limitations).
*   **Database:** SQLite (or PostgreSQL) - for demo simplicity.
*   **Hosting:** Docker Compose on a local machine (no cloud dependencies).

## Data Schema
The system will process two primary CSV files modeled after Cameroonian payroll structures.

**1. Employee Registry CSV:**
`matricule, full_name, national_id, phone, ministry, department, grade, duty_post_code, category, class_echelon, hire_date, location`

**2. Payroll CSV:**
`matricule, employee_name, base_salary, allowance_codes, total_salary, bank_name, bank_account, payment_date`
*(Demo allowance codes to support: housing, duty, representation, transport, family)*

## Architecture & API Design
The backend will utilize a simple, non-blocking architecture using FastAPI `BackgroundTasks` instead of complex queues like Celery/Redis.

*   **POST `/api/upload`**: Accepts the two CSV files, initiates the analysis pipeline as a background task, and returns a job ID.
*   **GET `/api/status/{job_id}`**: Polled by the frontend to get the progress/status of the background task.
*   **GET `/api/results/{job_id}`**: Retrieves the final structured JSON detection results.
*   **POST `/api/ai-summary/{job_id}`**: Generates the AI audit report on demand after the deterministic analysis is complete.

## The Core Pipeline (Step-by-Step)
The detection mechanism is entirely deterministic - the LLM is NOT used for detection.

### 1. Data Ingestion
*   Use Pandas to read both CSVs.
*   Normalize text: Trim whitespace, uppercase names for matching.
*   Validate columns against the expected schemas.

### 2. Exact-Match Detection
*   Identify duplicates using Pandas GroupBy: `groupby('national_id').filter(count > 1)`.
*   Apply the same logic for `bank_account` and `matricule`.

### 3. Blocked Fuzzy Name Matching
*   **Blocking:** Bucket names by the first letter of the surname (or Soundex) to avoid $O(n^2)$ comparisons.
*   **Matching:** Run RapidFuzz *only* within each bucket.
*   **Threshold:** Flag pairs with $\ge 85\%$ similarity.

### 4. Missing-Record Detection (Ghost Workers)
*   Vectorized set difference: `payroll_matricules - registry_matricules`.
*   Flags employees on the payroll who do not exist in the official registry.

### 5. Salary Anomaly Detection
*   **ML Layer:** Isolation Forest (via scikit-learn) on the salary distribution to catch unknown/unexpected patterns.
*   **Rule-Based Layer:** Optional expected-salary rules uploaded by the organization. Compare `total_salary` against rules based on `grade`, `duty_post_code`, and `class_echelon` only when a rules file is supplied.

### 6. Fraud Network Construction
*   Build a graph using NetworkX.
*   **Nodes:** Employees.
*   **Edges:** Shared `bank_account`, shared `national_id`, or fuzzy-matched `name`.
*   **Analysis:** Run connected components. Clusters of size 2 or more represent a potential fraud network.

### 7. Risk Scoring Engine
Calculate a weighted risk score per employee, capped at 100:
*   Duplicate ID: +30
*   Shared Account: +25
*   Missing Record: +20
*   Salary Anomaly: +15
*   Network Membership: +10
*   **Mapping:** Low (0-25), Moderate (26-50), High (51-75), Critical (76-100).

### 8. AI Report Generation (On-Demand Final Step)
*   Triggered only when the frontend calls `POST /api/ai-summary/{job_id}`, such as when a user clicks "Generate Report" on the AI audit page.
*   Feed the summarized statistical JSON output (e.g., flags, network sizes, and risk scores) from steps 2-7 into a prompt template via the Gemini API.
*   *Crucial Privacy Note*: Only the aggregated stats and anonymized risk summaries are pushed to the API, NEVER the entire dataset or raw PII.
*   The LLM's *only* job is to write a readable prose report explaining the findings based on those stats. It does not make detection decisions.
*   Cache the generated report in the job store so repeated clicks do not call Gemini again unless forced.

## Out of Scope for MVP
To ensure the MVP meets the 22 July deadline, the following features are explicitly excluded:
*   Multi-user authentication / Role-based access.
*   PDF export functionality.
*   Settings configuration page.
*   Live API integration with SIGIPES/AIGLES (post-MVP).
*   Redis/Celery for job queuing or chunked file streaming.
