from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
import os
import re
import uuid
import networkx as nx
import pandas as pd
from google import genai
from rapidfuzz import fuzz
from sklearn.ensemble import IsolationForest
from typing import Dict, List, Optional, Set
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Sentinel Gov Backend", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for demo simplicity (tracks background job status)
# In production, you'd use a real database.
jobs: Dict[str, dict] = {}

REGISTRY_REQUIRED_COLUMNS: Set[str] = {
    "matricule",
    "full_name",
    "national_id",
    "phone",
    "ministry",
    "department",
    "grade",
    "duty_post_code",
    "category",
    "class_echelon",
    "hire_date",
    "location",
}

PAYROLL_REQUIRED_COLUMNS: Set[str] = {
    "matricule",
    "employee_name",
    "base_salary",
    "allowance_codes",
    "total_salary",
    "bank_name",
    "bank_account",
    "payment_date",
}

REGISTRY_FRONTEND_COLUMNS: List[str] = [
    "matricule",
    "full_name",
    "national_id",
    "phone",
    "ministry",
    "department",
    "grade",
    "duty_post_code",
    "category",
    "class_echelon",
    "hire_date",
    "location",
]

PAYROLL_FRONTEND_COLUMNS: List[str] = [
    "matricule",
    "employee_name",
    "base_salary",
    "allowance_codes",
    "total_salary",
    "bank_name",
    "bank_account",
    "payment_date",
]

SALARY_RULE_REQUIRED_COLUMNS: Set[str] = {
    "grade",
    "duty_post_code",
    "class_echelon",
    "expected_salary",
}

FUZZY_NAME_THRESHOLD = 85
FUZZY_BLOCK_PREFIX_LENGTH = 3
MAX_FUZZY_CANDIDATE_PAIRS = 1_000_000
MAX_FUZZY_MATCHES_RETURNED = 10_000
MAX_PAIRWISE_SHARED_VALUE_GROUP_SIZE = 50
SALARY_RULE_TOLERANCE = 0.20
MIN_ML_SALARY_RECORDS = 8
SALARY_ML_CONTAMINATION = 0.05
RISK_WEIGHTS = {
    "duplicate_id": 30,
    "shared_bank_account": 25,
    "ghost_worker": 20,
    "fuzzy_name_match": 15,
    "salary_anomaly": 15,
    "network_membership": 10,
}
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TOP_RISK_RECORDS_FOR_REPORT = 10
FINANCIAL_EXPOSURE_CURRENCY = "FCFA"
DEFAULT_REPORT_LANGUAGE = "en"
SUPPORTED_REPORT_LANGUAGES = {
    "en": "English",
    "fr": "French",
}
REPORT_SECTION_HEADINGS = {
    "en": (
        "Executive Summary, Key Findings, Risk Distribution, Fraud Networks, "
        "Salary Anomalies, Recommended Next Steps, Data And Privacy Notes"
    ),
    "fr": (
        "Resume Executif, Principaux Constats, Repartition du Risque, "
        "Reseaux de Fraude, Anomalies Salariales, Prochaines Etapes "
        "Recommandees, Notes sur les Donnees et la Confidentialite"
    ),
}

def read_and_normalize_csv(file_path: str) -> pd.DataFrame:
    df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
    df.columns = df.columns.str.strip().str.lower()

    for col in df.columns:
        df[col] = df[col].str.strip()

    for name_col in ["full_name", "employee_name"]:
        if name_col in df.columns:
            df[name_col] = df[name_col].str.upper()

    return df

def validate_required_columns(df: pd.DataFrame, required_columns: Set[str], file_label: str):
    missing_columns = sorted(required_columns - set(df.columns))
    if missing_columns:
        missing = ", ".join(missing_columns)
        raise ValueError(f"{file_label} is missing required columns: {missing}")

def read_csv_header_columns(file_path: str) -> Set[str]:
    try:
        columns = pd.read_csv(file_path, dtype=str, nrows=0).columns
    except pd.errors.EmptyDataError:
        return set()

    return set(columns.str.strip().str.lower())

def validate_csv_file_headers(
    file_path: str,
    required_columns: Set[str],
    file_label: str,
) -> Optional[dict]:
    received_columns = read_csv_header_columns(file_path)
    missing_columns = sorted(required_columns - received_columns)

    if not missing_columns:
        return None

    return {
        "file": file_label,
        "missing_columns": missing_columns,
        "required_columns": sorted(required_columns),
        "received_columns": sorted(received_columns),
    }

def existing_columns(df: pd.DataFrame, columns: List[str]) -> List[str]:
    return [col for col in columns if col in df.columns]

def dataframe_records(df: pd.DataFrame, columns: List[str]) -> List[dict]:
    selected_columns = existing_columns(df, columns)
    return df[selected_columns].to_dict(orient="records")

def find_duplicate_records(df: pd.DataFrame, column: str, output_columns: List[str]) -> dict:
    records_with_value = df[df[column] != ""]
    duplicate_rows = records_with_value[
        records_with_value.duplicated(subset=[column], keep=False)
    ]

    selected_columns = existing_columns(df, output_columns)
    duplicate_values = sorted(duplicate_rows[column].unique().tolist())
    duplicate_records = (
        duplicate_rows[selected_columns]
        .sort_values(by=column)
        .to_dict(orient="records")
    )

    return {
        "duplicate_value_count": len(duplicate_values),
        "affected_record_count": len(duplicate_records),
        "duplicate_values": duplicate_values,
        "records": duplicate_records,
    }

def normalize_name_tokens(name: str) -> List[str]:
    cleaned_name = "".join(
        char if char.isalnum() or char.isspace() else " "
        for char in name.upper()
    )
    return [part for part in cleaned_name.split() if part]

def name_block_keys(name: str) -> List[str]:
    name_parts = [part for part in name.split() if part]
    if not name_parts:
        return []

    tokens = normalize_name_tokens(name)
    if not tokens:
        return []

    sorted_tokens = sorted(tokens)
    first_token = sorted_tokens[0][:FUZZY_BLOCK_PREFIX_LENGTH]
    last_token = sorted_tokens[-1][:FUZZY_BLOCK_PREFIX_LENGTH]
    token_count = min(len(sorted_tokens), 4)

    return [f"{first_token}|{last_token}|{token_count}"]

def build_name_records(df: pd.DataFrame, name_column: str, output_columns: List[str]) -> List[dict]:
    selected_columns = existing_columns(df, output_columns)
    records = []

    for row_index, row in df[df[name_column] != ""].iterrows():
        records.append({
            "row_index": int(row_index),
            "name": row[name_column],
            "details": row[selected_columns].to_dict(),
        })

    return records

def find_blocked_fuzzy_name_matches(
    df: pd.DataFrame,
    name_column: str,
    output_columns: List[str],
    threshold: int = FUZZY_NAME_THRESHOLD,
) -> dict:
    name_records = build_name_records(df, name_column, output_columns)
    buckets: Dict[str, List[dict]] = {}

    for record in name_records:
        for key in name_block_keys(record["name"]):
            buckets.setdefault(key, []).append(record)

    matches = []
    match_count = 0
    candidate_pair_count = 0
    skipped_candidate_pair_count = 0
    candidate_limit_reached = False

    for bucket_records in buckets.values():
        if candidate_limit_reached:
            skipped_candidate_pair_count += len(bucket_records) * (len(bucket_records) - 1) // 2
            continue

        for left_index in range(len(bucket_records)):
            for right_index in range(left_index + 1, len(bucket_records)):
                if candidate_pair_count >= MAX_FUZZY_CANDIDATE_PAIRS:
                    remaining_in_bucket = (
                        len(bucket_records) - right_index
                    )
                    remaining_after_left = sum(
                        len(bucket_records) - next_left_index - 1
                        for next_left_index in range(
                            left_index + 1,
                            len(bucket_records),
                        )
                    )
                    skipped_candidate_pair_count += remaining_in_bucket + remaining_after_left
                    candidate_limit_reached = True
                    break

                left = bucket_records[left_index]
                right = bucket_records[right_index]

                left_matricule = left["details"].get("matricule")
                right_matricule = right["details"].get("matricule")
                if left_matricule and left_matricule == right_matricule:
                    continue

                candidate_pair_count += 1
                score = fuzz.token_sort_ratio(left["name"], right["name"])

                if score >= threshold:
                    match_count += 1
                    if len(matches) < MAX_FUZZY_MATCHES_RETURNED:
                        matches.append({
                            "score": round(score, 2),
                            "left": left["details"],
                            "right": right["details"],
                        })

            if candidate_limit_reached:
                break

    matches.sort(key=lambda match: match["score"], reverse=True)

    return {
        "threshold": threshold,
        "blocking_rule": "sorted_token_prefix",
        "block_prefix_length": FUZZY_BLOCK_PREFIX_LENGTH,
        "record_count": len(name_records),
        "bucket_count": len(buckets),
        "unblocked_pair_count": len(name_records) * (len(name_records) - 1) // 2,
        "candidate_pair_count": candidate_pair_count,
        "candidate_limit": MAX_FUZZY_CANDIDATE_PAIRS,
        "candidate_limit_reached": candidate_limit_reached,
        "skipped_candidate_pair_count": skipped_candidate_pair_count,
        "max_matches_returned": MAX_FUZZY_MATCHES_RETURNED,
        "matches_truncated": match_count > len(matches),
        "match_count": match_count,
        "returned_match_count": len(matches),
        "matches": matches,
    }

def find_ghost_workers(registry_df: pd.DataFrame, payroll_df: pd.DataFrame) -> dict:
    payroll_matricules = set(payroll_df[payroll_df["matricule"] != ""]["matricule"])
    registry_matricules = set(registry_df[registry_df["matricule"] != ""]["matricule"])
    ghost_matricules = sorted(payroll_matricules - registry_matricules)

    output_columns = existing_columns(
        payroll_df,
        PAYROLL_FRONTEND_COLUMNS,
    )
    ghost_records = (
        payroll_df[payroll_df["matricule"].isin(ghost_matricules)][output_columns]
        .sort_values(by="matricule")
        .to_dict(orient="records")
    )

    return {
        "ghost_worker_count": len(ghost_matricules),
        "matricules": ghost_matricules,
        "records": ghost_records,
    }

def parse_money_column(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.replace(r"[^0-9.-]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")

def parse_tolerance_value(value, default: float = SALARY_RULE_TOLERANCE) -> float:
    if pd.isna(value):
        return default

    text_value = str(value).strip().replace("%", "")
    if not text_value:
        return default

    parsed = pd.to_numeric(pd.Series([text_value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return default

    parsed = float(parsed)
    if parsed > 1:
        parsed = parsed / 100

    return parsed

def salary_rule_key(row: pd.Series) -> tuple:
    return (
        str(row.get("grade", "")).strip().upper(),
        str(row.get("duty_post_code", "")).strip().upper(),
        str(row.get("class_echelon", "")).strip().upper(),
    )

def read_salary_rules_csv(file_path: str) -> pd.DataFrame:
    salary_rules_df = read_and_normalize_csv(file_path)
    validate_required_columns(
        salary_rules_df,
        SALARY_RULE_REQUIRED_COLUMNS,
        "Salary rules CSV",
    )
    salary_rules_df["expected_salary_number"] = parse_money_column(
        salary_rules_df["expected_salary"]
    )

    return salary_rules_df

def build_salary_rule_lookup(salary_rules_df: Optional[pd.DataFrame]) -> dict:
    if salary_rules_df is None:
        return {
            "enabled": False,
            "reason": "No salary rules file was supplied.",
            "rules": {},
            "rules_loaded": 0,
            "invalid_rule_count": 0,
            "duplicate_rule_count": 0,
        }

    salary_rules_df = salary_rules_df.copy()
    salary_rules_df.columns = salary_rules_df.columns.str.strip().str.lower()
    validate_required_columns(
        salary_rules_df,
        SALARY_RULE_REQUIRED_COLUMNS,
        "Salary rules CSV",
    )
    if "expected_salary_number" not in salary_rules_df.columns:
        salary_rules_df["expected_salary_number"] = parse_money_column(
            salary_rules_df["expected_salary"]
        )

    rule_lookup = {}
    invalid_rule_count = 0
    duplicate_rule_count = 0

    for _, row in salary_rules_df.iterrows():
        key = salary_rule_key(row)
        expected_salary = row["expected_salary_number"]

        if "" in key or pd.isna(expected_salary):
            invalid_rule_count += 1
            continue

        if key in rule_lookup:
            duplicate_rule_count += 1

        tolerance = SALARY_RULE_TOLERANCE
        if "tolerance" in salary_rules_df.columns:
            tolerance = parse_tolerance_value(row.get("tolerance"))

        rule_lookup[key] = {
            "expected_salary": float(expected_salary),
            "tolerance": tolerance,
        }

    if not rule_lookup:
        return {
            "enabled": False,
            "reason": "No valid salary rules were found in the supplied file.",
            "rules": {},
            "rules_loaded": 0,
            "invalid_rule_count": invalid_rule_count,
            "duplicate_rule_count": duplicate_rule_count,
        }

    return {
        "enabled": True,
        "reason": "Salary rules file supplied.",
        "rules": rule_lookup,
        "rules_loaded": len(rule_lookup),
        "invalid_rule_count": invalid_rule_count,
        "duplicate_rule_count": duplicate_rule_count,
    }

def safe_row_value(row: pd.Series, column: str):
    value = row.get(column, "")
    if pd.isna(value):
        return ""
    return value

def row_values(row: pd.Series, columns: List[str]) -> dict:
    return {column: safe_row_value(row, column) for column in columns}

def salary_record(row: pd.Series) -> dict:
    record = row_values(row, REGISTRY_FRONTEND_COLUMNS)
    record.update(row_values(
        row,
        [column for column in PAYROLL_FRONTEND_COLUMNS if column != "matricule"],
    ))
    record["matricule"] = safe_row_value(row, "matricule")
    return record

def build_salary_analysis_df(registry_df: pd.DataFrame, payroll_df: pd.DataFrame) -> pd.DataFrame:
    salary_df = payroll_df.merge(
        registry_df[REGISTRY_FRONTEND_COLUMNS],
        on="matricule",
        how="left",
    )
    salary_df["total_salary_number"] = parse_money_column(salary_df["total_salary"])

    return salary_df

def find_rule_based_salary_anomalies(
    salary_df: pd.DataFrame,
    salary_rules_df: Optional[pd.DataFrame],
) -> dict:
    rule_info = build_salary_rule_lookup(salary_rules_df)
    if not rule_info["enabled"]:
        return {
            "enabled": False,
            "reason": rule_info["reason"],
            "default_tolerance": SALARY_RULE_TOLERANCE,
            "rules_loaded": rule_info["rules_loaded"],
            "invalid_rule_count": rule_info["invalid_rule_count"],
            "duplicate_rule_count": rule_info["duplicate_rule_count"],
            "records_checked": 0,
            "missing_rule_count": 0,
            "invalid_salary_count": 0,
            "anomaly_count": 0,
            "records": [],
        }

    anomalies = []
    missing_rule_count = 0
    invalid_salary_count = 0
    records_checked = 0
    rule_lookup = rule_info["rules"]

    for _, row in salary_df.iterrows():
        actual_salary = row["total_salary_number"]
        if pd.isna(actual_salary):
            invalid_salary_count += 1
            continue

        rule = rule_lookup.get(salary_rule_key(row))
        if rule is None:
            missing_rule_count += 1
            continue

        expected_salary = rule["expected_salary"]
        tolerance = rule["tolerance"]
        records_checked += 1
        allowed_min = expected_salary * (1 - tolerance)
        allowed_max = expected_salary * (1 + tolerance)

        if actual_salary < allowed_min or actual_salary > allowed_max:
            record = salary_record(row)
            record.update({
                "actual_salary": round(float(actual_salary), 2),
                "expected_salary": round(float(expected_salary), 2),
                "tolerance": tolerance,
                "allowed_min": round(allowed_min, 2),
                "allowed_max": round(allowed_max, 2),
                "difference": round(float(actual_salary - expected_salary), 2),
            })
            anomalies.append(record)

    return {
        "enabled": True,
        "reason": rule_info["reason"],
        "default_tolerance": SALARY_RULE_TOLERANCE,
        "rules_loaded": rule_info["rules_loaded"],
        "invalid_rule_count": rule_info["invalid_rule_count"],
        "duplicate_rule_count": rule_info["duplicate_rule_count"],
        "records_checked": records_checked,
        "missing_rule_count": missing_rule_count,
        "invalid_salary_count": invalid_salary_count,
        "anomaly_count": len(anomalies),
        "records": anomalies,
    }

def find_statistical_salary_anomalies(salary_df: pd.DataFrame) -> dict:
    valid_salary_df = salary_df.dropna(subset=["total_salary_number"]).copy()

    if len(valid_salary_df) < MIN_ML_SALARY_RECORDS:
        return {
            "enabled": False,
            "reason": "Not enough valid salary records for Isolation Forest.",
            "minimum_required_records": MIN_ML_SALARY_RECORDS,
            "records_checked": len(valid_salary_df),
            "anomaly_count": 0,
            "records": [],
        }

    model = IsolationForest(
        contamination=SALARY_ML_CONTAMINATION,
        random_state=42,
    )
    salaries = valid_salary_df[["total_salary_number"]]
    predictions = model.fit_predict(salaries)
    scores = model.decision_function(salaries)

    valid_salary_df["ml_prediction"] = predictions
    valid_salary_df["ml_score"] = scores
    anomaly_rows = valid_salary_df[valid_salary_df["ml_prediction"] == -1]

    records = []
    for _, row in anomaly_rows.sort_values(by="ml_score").iterrows():
        record = salary_record(row)
        record.update({
            "actual_salary": round(float(row["total_salary_number"]), 2),
            "ml_score": round(float(row["ml_score"]), 6),
        })
        records.append(record)

    return {
        "enabled": True,
        "method": "IsolationForest",
        "contamination": SALARY_ML_CONTAMINATION,
        "records_checked": len(valid_salary_df),
        "anomaly_count": len(records),
        "records": records,
    }

def detect_salary_anomalies(
    registry_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
    salary_rules_df: Optional[pd.DataFrame] = None,
) -> dict:
    salary_df = build_salary_analysis_df(registry_df, payroll_df)

    return {
        "rule_based": find_rule_based_salary_anomalies(salary_df, salary_rules_df),
        "statistical": find_statistical_salary_anomalies(salary_df),
    }

def calculate_financial_exposure(ghost_worker_findings: dict, salary_anomaly_findings: dict) -> dict:
    ghost_worker_exposure = 0.0
    for record in ghost_worker_findings.get("records", []):
        val = str(record.get("total_salary", "0"))
        cleaned = re.sub(r"[^0-9.-]", "", val)
        if cleaned:
            try:
                ghost_worker_exposure += float(cleaned)
            except ValueError:
                pass

    rule_salary_overpayment_exposure = 0.0
    for record in salary_anomaly_findings.get("rule_based", {}).get("records", []):
        diff = record.get("difference", 0)
        if isinstance(diff, (int, float)) and diff > 0:
            rule_salary_overpayment_exposure += float(diff)

    estimated_total = ghost_worker_exposure + rule_salary_overpayment_exposure

    return {
        "currency": FINANCIAL_EXPOSURE_CURRENCY,
        "estimated_total": round(estimated_total, 2),
        "ghost_worker_exposure": round(ghost_worker_exposure, 2),
        "salary_rule_overpayment_exposure": round(rule_salary_overpayment_exposure, 2),
        "statistical_salary_anomaly_exposure": None,
        "note": "Statistical salary anomalies are excluded from estimated exposure unless a salary rule expected value exists."
    }

def employee_node_details(matricule: str, registry_row=None, payroll_row=None) -> dict:
    details = {column: "" for column in REGISTRY_FRONTEND_COLUMNS}
    details.update({
        column: ""
        for column in PAYROLL_FRONTEND_COLUMNS
        if column != "matricule"
    })
    details["matricule"] = matricule

    if registry_row is not None:
        details.update(row_values(registry_row, REGISTRY_FRONTEND_COLUMNS))

    if payroll_row is not None:
        details.update(row_values(
            payroll_row,
            [column for column in PAYROLL_FRONTEND_COLUMNS if column != "matricule"],
        ))

    details["matricule"] = matricule

    return details

def add_employee_nodes(graph: nx.Graph, registry_df: pd.DataFrame, payroll_df: pd.DataFrame):
    registry_by_matricule = {
        row["matricule"]: row
        for _, row in registry_df[registry_df["matricule"] != ""].iterrows()
    }
    payroll_by_matricule = {
        row["matricule"]: row
        for _, row in payroll_df[payroll_df["matricule"] != ""].iterrows()
    }

    all_matricules = sorted(set(registry_by_matricule) | set(payroll_by_matricule))
    for matricule in all_matricules:
        graph.add_node(
            matricule,
            details=employee_node_details(
                matricule,
                registry_by_matricule.get(matricule),
                payroll_by_matricule.get(matricule),
            ),
        )

def add_fraud_edge(
    graph: nx.Graph,
    left_matricule: str,
    right_matricule: str,
    reason: str,
    evidence: dict,
):
    if not left_matricule or not right_matricule or left_matricule == right_matricule:
        return

    if not graph.has_node(left_matricule):
        graph.add_node(left_matricule, details={"matricule": left_matricule})
    if not graph.has_node(right_matricule):
        graph.add_node(right_matricule, details={"matricule": right_matricule})

    if not graph.has_edge(left_matricule, right_matricule):
        graph.add_edge(left_matricule, right_matricule, reasons=[], evidence=[])

    edge_data = graph[left_matricule][right_matricule]
    if reason not in edge_data["reasons"]:
        edge_data["reasons"].append(reason)
    edge_data["evidence"].append(evidence)

def add_shared_value_edges(
    graph: nx.Graph,
    df: pd.DataFrame,
    column: str,
    reason: str,
) -> int:
    if column not in df.columns:
        return 0

    usable_rows = df[(df["matricule"] != "") & (df[column] != "")]
    edges_added = 0

    for shared_value, group in usable_rows.groupby(column):
        matricules = sorted(set(group["matricule"]))
        if len(matricules) < 2:
            continue

        if len(matricules) > MAX_PAIRWISE_SHARED_VALUE_GROUP_SIZE:
            hub_matricule = matricules[0]
            for right_matricule in matricules[1:]:
                add_fraud_edge(
                    graph,
                    hub_matricule,
                    right_matricule,
                    reason,
                    {
                        "reason": reason,
                        "matched_field": column,
                        "shared_value": shared_value,
                        "shared_group_size": len(matricules),
                        "edge_strategy": "star_for_large_shared_value_group",
                    },
                )
                edges_added += 1
            continue

        for left_index in range(len(matricules)):
            for right_index in range(left_index + 1, len(matricules)):
                add_fraud_edge(
                    graph,
                    matricules[left_index],
                    matricules[right_index],
                    reason,
                    {
                        "reason": reason,
                        "matched_field": column,
                        "shared_value": shared_value,
                        "shared_group_size": len(matricules),
                        "edge_strategy": "pairwise",
                    },
                )
                edges_added += 1

    return edges_added

def add_fuzzy_name_edges(graph: nx.Graph, fuzzy_name_checks: dict) -> int:
    edges_added = 0

    for source, check_result in fuzzy_name_checks.items():
        for match in check_result.get("matches", []):
            left = match.get("left", {})
            right = match.get("right", {})
            left_matricule = left.get("matricule", "")
            right_matricule = right.get("matricule", "")

            add_fraud_edge(
                graph,
                left_matricule,
                right_matricule,
                "fuzzy_name_match",
                {
                    "reason": "fuzzy_name_match",
                    "source": source,
                    "score": match.get("score"),
                    "left_name": left.get("full_name") or left.get("employee_name"),
                    "right_name": right.get("full_name") or right.get("employee_name"),
                },
            )
            if left_matricule and right_matricule and left_matricule != right_matricule:
                edges_added += 1

    return edges_added

def serialize_network_edge(left: str, right: str, edge_data: dict) -> dict:
    return {
        "left": left,
        "right": right,
        "reasons": sorted(edge_data.get("reasons", [])),
        "evidence": edge_data.get("evidence", []),
    }

def build_fraud_networks(
    registry_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
    fuzzy_name_checks: dict,
) -> dict:
    graph = nx.Graph()
    add_employee_nodes(graph, registry_df, payroll_df)
    shared_bank_edges = add_shared_value_edges(
        graph,
        payroll_df,
        "bank_account",
        "shared_bank_account",
    )
    shared_national_id_edges = add_shared_value_edges(
        graph,
        registry_df,
        "national_id",
        "shared_national_id",
    )
    fuzzy_name_edges = add_fuzzy_name_edges(graph, fuzzy_name_checks)

    networks = []
    for component in nx.connected_components(graph):
        subgraph = graph.subgraph(component)
        if subgraph.number_of_nodes() < 2 or subgraph.number_of_edges() == 0:
            continue

        reasons = set()
        edges = []
        for left, right, edge_data in subgraph.edges(data=True):
            reasons.update(edge_data.get("reasons", []))
            edges.append(serialize_network_edge(left, right, edge_data))

        members = [
            graph.nodes[matricule].get("details", {"matricule": matricule})
            for matricule in sorted(component)
        ]

        networks.append({
            "network_id": len(networks) + 1,
            "size": subgraph.number_of_nodes(),
            "member_matricules": sorted(component),
            "members": members,
            "reasons": sorted(reasons),
            "edge_count": subgraph.number_of_edges(),
            "edges": sorted(edges, key=lambda edge: (edge["left"], edge["right"])),
        })

    networks.sort(key=lambda network: network["size"], reverse=True)
    for index, network in enumerate(networks, start=1):
        network["network_id"] = index

    return {
        "algorithm": "undirected_graph_connected_components",
        "node_count": graph.number_of_nodes(),
        "edge_count": graph.number_of_edges(),
        "network_count": len(networks),
        "edge_sources": {
            "shared_bank_account_edges": shared_bank_edges,
            "shared_national_id_edges": shared_national_id_edges,
            "fuzzy_name_edges": fuzzy_name_edges,
        },
        "networks": networks,
    }

def risk_level_for_score(score: int) -> str:
    if score == 0:
        return "None"
    if score <= 25:
        return "Low"
    if score <= 50:
        return "Moderate"
    if score <= 75:
        return "High"
    return "Critical"

def empty_risk_record(matricule: str) -> dict:
    record = employee_node_details(matricule)
    record.update({
        "raw_score": 0,
        "risk_score": 0,
        "risk_level": "None",
        "risk_factors": [],
        "_factor_map": {},
    })
    return record

def build_risk_records(registry_df: pd.DataFrame, payroll_df: pd.DataFrame) -> dict:
    registry_by_matricule = {
        row["matricule"]: row
        for _, row in registry_df[registry_df["matricule"] != ""].iterrows()
    }
    payroll_by_matricule = {
        row["matricule"]: row
        for _, row in payroll_df[payroll_df["matricule"] != ""].iterrows()
    }

    risk_records = {}
    all_matricules = sorted(set(registry_by_matricule) | set(payroll_by_matricule))
    for matricule in all_matricules:
        record = empty_risk_record(matricule)
        record.update(
            employee_node_details(
                matricule,
                registry_by_matricule.get(matricule),
                payroll_by_matricule.get(matricule),
            )
        )
        risk_records[matricule] = record

    return risk_records

def add_risk_factor(
    risk_records: dict,
    matricule: str,
    factor: str,
    evidence: dict,
):
    if not matricule:
        return

    if matricule not in risk_records:
        risk_records[matricule] = empty_risk_record(matricule)

    record = risk_records[matricule]
    factor_map = record["_factor_map"]
    if factor not in factor_map:
        factor_map[factor] = {
            "factor": factor,
            "points": RISK_WEIGHTS[factor],
            "evidence": [],
        }
        record["raw_score"] += RISK_WEIGHTS[factor]

    factor_map[factor]["evidence"].append(evidence)

def add_duplicate_id_risks(risk_records: dict, duplicate_checks: dict):
    duplicate_sources = [
        (
            "registry_duplicate_national_ids",
            "national_id",
            "registry",
        ),
        (
            "registry_duplicate_matricules",
            "matricule",
            "registry",
        ),
        (
            "payroll_duplicate_matricules",
            "matricule",
            "payroll",
        ),
    ]

    for check_name, id_field, source in duplicate_sources:
        for record in duplicate_checks[check_name]["records"]:
            add_risk_factor(
                risk_records,
                record.get("matricule", ""),
                "duplicate_id",
                {
                    "source": source,
                    "id_field": id_field,
                    "id_value": record.get(id_field, ""),
                    "name": record.get("full_name") or record.get("employee_name", ""),
                },
            )

def add_shared_account_risks(risk_records: dict, duplicate_checks: dict):
    for record in duplicate_checks["payroll_duplicate_bank_accounts"]["records"]:
        add_risk_factor(
            risk_records,
            record.get("matricule", ""),
            "shared_bank_account",
            {
                "bank_account": record.get("bank_account", ""),
                "employee_name": record.get("employee_name", ""),
                "bank_name": record.get("bank_name", ""),
            },
        )

def add_ghost_worker_risks(risk_records: dict, ghost_worker_findings: dict):
    for record in ghost_worker_findings.get("records", []):
        add_risk_factor(
            risk_records,
            record.get("matricule", ""),
            "ghost_worker",
            {
                "employee_name": record.get("employee_name", ""),
                "total_salary": record.get("total_salary", ""),
                "bank_account": record.get("bank_account", ""),
            },
        )

def add_salary_anomaly_risks(risk_records: dict, salary_anomaly_findings: dict):
    for source in ["rule_based", "statistical"]:
        for record in salary_anomaly_findings.get(source, {}).get("records", []):
            add_risk_factor(
                risk_records,
                record.get("matricule", ""),
                "salary_anomaly",
                {
                    "source": source,
                    "actual_salary": record.get("actual_salary"),
                    "expected_salary": record.get("expected_salary"),
                    "ml_score": record.get("ml_score"),
                },
            )

def add_fuzzy_name_risks(risk_records: dict, fuzzy_name_checks: dict):
    for source, check_result in fuzzy_name_checks.items():
        for match in check_result.get("matches", []):
            left = match.get("left", {})
            right = match.get("right", {})
            left_matricule = left.get("matricule", "")
            right_matricule = right.get("matricule", "")
            
            if left_matricule:
                add_risk_factor(
                    risk_records,
                    left_matricule,
                    "fuzzy_name_match",
                    {
                        "source": source,
                        "matched_matricule": right_matricule,
                        "score": match.get("score"),
                        "matched_name": right.get("full_name") or right.get("employee_name", ""),
                    },
                )
            if right_matricule:
                add_risk_factor(
                    risk_records,
                    right_matricule,
                    "fuzzy_name_match",
                    {
                        "source": source,
                        "matched_matricule": left_matricule,
                        "score": match.get("score"),
                        "matched_name": left.get("full_name") or left.get("employee_name", ""),
                    },
                )

def add_network_membership_risks(risk_records: dict, fraud_network_findings: dict):
    for network in fraud_network_findings.get("networks", []):
        for matricule in network.get("member_matricules", []):
            add_risk_factor(
                risk_records,
                matricule,
                "network_membership",
                {
                    "network_id": network.get("network_id"),
                    "network_size": network.get("size"),
                    "network_reasons": network.get("reasons", []),
                },
            )

def finalize_risk_records(risk_records: dict) -> List[dict]:
    finalized_records = []

    for record in risk_records.values():
        record["risk_score"] = min(record["raw_score"], 100)
        record["risk_level"] = risk_level_for_score(record["risk_score"])
        record["risk_factors"] = sorted(
            record["_factor_map"].values(),
            key=lambda factor: factor["factor"],
        )
        del record["_factor_map"]
        finalized_records.append(record)

    return sorted(
        finalized_records,
        key=lambda record: (-record["risk_score"], record["matricule"]),
    )

def build_risk_summary(records: List[dict]) -> dict:
    level_counts = {
        "None": 0,
        "Low": 0,
        "Moderate": 0,
        "High": 0,
        "Critical": 0,
    }
    employees_with_risk = 0
    highest_risk_score = 0

    for record in records:
        level_counts[record["risk_level"]] += 1
        if record["risk_score"] > 0:
            employees_with_risk += 1
        highest_risk_score = max(highest_risk_score, record["risk_score"])

    return {
        "employee_count": len(records),
        "employees_with_risk": employees_with_risk,
        "highest_risk_score": highest_risk_score,
        "level_counts": level_counts,
    }

def calculate_risk_scores(
    registry_df: pd.DataFrame,
    payroll_df: pd.DataFrame,
    duplicate_checks: dict,
    fuzzy_name_checks: dict,
    ghost_worker_findings: dict,
    salary_anomaly_findings: dict,
    fraud_network_findings: dict,
) -> dict:
    risk_records = build_risk_records(registry_df, payroll_df)

    add_duplicate_id_risks(risk_records, duplicate_checks)
    add_shared_account_risks(risk_records, duplicate_checks)
    add_fuzzy_name_risks(risk_records, fuzzy_name_checks)
    add_ghost_worker_risks(risk_records, ghost_worker_findings)
    add_salary_anomaly_risks(risk_records, salary_anomaly_findings)
    add_network_membership_risks(risk_records, fraud_network_findings)

    records = finalize_risk_records(risk_records)

    return {
        "weights": RISK_WEIGHTS,
        "level_mapping": {
            "None": "0",
            "Low": "1-25",
            "Moderate": "26-50",
            "High": "51-75",
            "Critical": "76-100",
        },
        "summary": build_risk_summary(records),
        "records": records,
    }

def anonymized_risk_record(record: dict, index: int) -> dict:
    return {
        "employee_ref": f"employee_{index}",
        "risk_score": record.get("risk_score", 0),
        "risk_level": record.get("risk_level", "Low"),
        "risk_factors": [
            {
                "factor": factor.get("factor"),
                "points": factor.get("points"),
                "evidence_count": len(factor.get("evidence", [])),
            }
            for factor in record.get("risk_factors", [])
        ],
    }

def summarize_network_for_report(network: dict) -> dict:
    return {
        "network_id": network.get("network_id"),
        "size": network.get("size"),
        "edge_count": network.get("edge_count"),
        "reasons": network.get("reasons", []),
    }

def build_report_payload(
    stats: dict,
    exact_match_findings: dict,
    fuzzy_name_findings: dict,
    ghost_worker_findings: dict,
    salary_anomaly_findings: dict,
    fraud_network_findings: dict,
    risk_score_findings: dict,
    financial_exposure: dict,
) -> dict:
    top_risk_records = [
        anonymized_risk_record(record, index)
        for index, record in enumerate(
            risk_score_findings.get("records", [])[:TOP_RISK_RECORDS_FOR_REPORT],
            start=1,
        )
    ]
    largest_networks = sorted(
        fraud_network_findings.get("networks", []),
        key=lambda network: network.get("size", 0),
        reverse=True,
    )[:5]

    return {
        "privacy_note": (
            "This payload excludes raw CSV rows, names, national IDs, bank accounts, "
            "and full employee identifiers. It contains summary statistics only."
        ),
        "analysis_scope": {
            "total_registry_records": stats["total_registry_records"],
            "total_payroll_records": stats["total_payroll_records"],
        },
        "finding_counts": {
            "duplicate_national_ids_found": stats["duplicate_national_ids_found"],
            "duplicate_bank_accounts_found": stats["duplicate_bank_accounts_found"],
            "duplicate_registry_matricules_found": stats["duplicate_registry_matricules_found"],
            "duplicate_payroll_matricules_found": stats["duplicate_payroll_matricules_found"],
            "registry_fuzzy_name_matches_found": stats["registry_fuzzy_name_matches_found"],
            "payroll_fuzzy_name_matches_found": stats["payroll_fuzzy_name_matches_found"],
            "potential_ghost_workers": stats["potential_ghost_workers"],
            "salary_rule_anomalies_found": stats["salary_rule_anomalies_found"],
            "salary_statistical_anomalies_found": stats["salary_statistical_anomalies_found"],
            "fraud_networks_found": stats["fraud_networks_found"],
        },
        "exact_match_summary": {
            key: {
                "duplicate_value_count": value.get("duplicate_value_count", 0),
                "affected_record_count": value.get("affected_record_count", 0),
            }
            for key, value in exact_match_findings.items()
        },
        "fuzzy_name_summary": {
            key: {
                "threshold": value.get("threshold"),
                "candidate_pair_count": value.get("candidate_pair_count", 0),
                "match_count": value.get("match_count", 0),
            }
            for key, value in fuzzy_name_findings.items()
        },
        "ghost_worker_summary": {
            "ghost_worker_count": ghost_worker_findings.get("ghost_worker_count", 0),
        },
        "salary_anomaly_summary": {
            "rule_based": {
                "enabled": salary_anomaly_findings.get("rule_based", {}).get("enabled"),
                "reason": salary_anomaly_findings.get("rule_based", {}).get("reason"),
                "anomaly_count": salary_anomaly_findings.get("rule_based", {}).get("anomaly_count", 0),
                "records_checked": salary_anomaly_findings.get("rule_based", {}).get("records_checked", 0),
            },
            "statistical": {
                "enabled": salary_anomaly_findings.get("statistical", {}).get("enabled"),
                "reason": salary_anomaly_findings.get("statistical", {}).get("reason"),
                "method": salary_anomaly_findings.get("statistical", {}).get("method"),
                "anomaly_count": salary_anomaly_findings.get("statistical", {}).get("anomaly_count", 0),
                "records_checked": salary_anomaly_findings.get("statistical", {}).get("records_checked", 0),
            },
        },
        "fraud_network_summary": {
            "algorithm": fraud_network_findings.get("algorithm"),
            "network_count": fraud_network_findings.get("network_count", 0),
            "node_count": fraud_network_findings.get("node_count", 0),
            "edge_count": fraud_network_findings.get("edge_count", 0),
            "edge_sources": fraud_network_findings.get("edge_sources", {}),
            "largest_networks": [
                summarize_network_for_report(network)
                for network in largest_networks
            ],
        },
        "financial_exposure": financial_exposure,
        "risk_summary": risk_score_findings.get("summary", {}),
        "risk_weights": risk_score_findings.get("weights", {}),
        "top_risk_records": top_risk_records,
    }

def normalize_report_language(language: str) -> str:
    normalized = (language or DEFAULT_REPORT_LANGUAGE).strip().lower().replace("_", "-")
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("fr"):
        return "fr"
    raise HTTPException(
        status_code=400,
        detail={
            "message": "Unsupported AI report language.",
            "language": language,
            "supported_languages": sorted(SUPPORTED_REPORT_LANGUAGES.keys()),
        },
    )

def ai_summary_status_for_job(job: dict) -> str:
    statuses = list(job.get("ai_summary_status_by_language", {}).values())
    if not statuses:
        return job.get("ai_summary_status", "not_ready")
    if "generating" in statuses:
        return "generating"
    if "completed" in statuses:
        return "completed"
    if "failed" in statuses:
        return "failed"
    return "not_requested"

def build_ai_summary_marker(job_id: str, job: dict) -> dict:
    reports = job.get("ai_reports", {})
    language_statuses = job.get("ai_summary_status_by_language", {})
    status_by_language = {
        language: language_statuses.get(
            language,
            "completed" if language in reports else "not_requested",
        )
        for language in SUPPORTED_REPORT_LANGUAGES
    }

    return {
        "status": ai_summary_status_for_job(job),
        "generate_endpoint": f"/api/ai-summary/{job_id}",
        "default_language": DEFAULT_REPORT_LANGUAGE,
        "supported_languages": sorted(SUPPORTED_REPORT_LANGUAGES.keys()),
        "generated_languages": sorted(reports.keys()),
        "status_by_language": status_by_language,
    }

def build_report_prompt(report_payload: dict, language: str = DEFAULT_REPORT_LANGUAGE) -> str:
    language = normalize_report_language(language)
    payload_json = json.dumps(report_payload, indent=2)
    language_name = SUPPORTED_REPORT_LANGUAGES[language]
    section_headings = REPORT_SECTION_HEADINGS[language]

    return f"""
You are Sentinel Gov's report writer.

Write a concise payroll audit report from the JSON summary below.
Write the entire report in {language_name}. Do not switch languages.
Rules:
- Do not invent findings, counts, employee names, IDs, bank accounts, or legal conclusions.
- The detection was already done by deterministic code. Your job is explanation only.
- Use clear section headings in {language_name}: {section_headings}.
- Mention that salary rule checks are optional and may be skipped if no rules file was supplied.
- Keep the tone professional and suitable for an auditor or public-sector payroll reviewer.

JSON summary:
{payload_json}
""".strip()

def build_local_report(report_payload: dict, language: str = DEFAULT_REPORT_LANGUAGE) -> str:
    language = normalize_report_language(language)
    risk_summary = report_payload["risk_summary"]
    finding_counts = report_payload["finding_counts"]
    network_summary = report_payload["fraud_network_summary"]
    salary_summary = report_payload["salary_anomaly_summary"]

    if language == "fr":
        lines = [
            "Resume Executif",
            f"Sentinel Gov a examine {report_payload['analysis_scope']['total_registry_records']} dossiers du registre et {report_payload['analysis_scope']['total_payroll_records']} dossiers de paie.",
            f"{risk_summary.get('employees_with_risk', 0)} employes presentent au moins un facteur de risque. Le score de risque le plus eleve est {risk_summary.get('highest_risk_score', 0)}.",
            "",
            "Principaux Constats",
            f"- Identifiants nationaux dupliques trouves: {finding_counts['duplicate_national_ids_found']}",
            f"- Comptes bancaires dupliques trouves: {finding_counts['duplicate_bank_accounts_found']}",
            f"- Travailleurs fantomes potentiels trouves: {finding_counts['potential_ghost_workers']}",
            f"- Correspondances de noms approximatives trouvees: {finding_counts['registry_fuzzy_name_matches_found'] + finding_counts['payroll_fuzzy_name_matches_found']}",
            f"- Reseaux de fraude trouves: {finding_counts['fraud_networks_found']}",
            "",
            "Repartition du Risque",
            f"- Aucun risque: {risk_summary.get('level_counts', {}).get('None', 0)}",
            f"- Faible: {risk_summary.get('level_counts', {}).get('Low', 0)}",
            f"- Modere: {risk_summary.get('level_counts', {}).get('Moderate', 0)}",
            f"- Eleve: {risk_summary.get('level_counts', {}).get('High', 0)}",
            f"- Critique: {risk_summary.get('level_counts', {}).get('Critical', 0)}",
            "",
            "Reseaux de Fraude",
            f"L'analyse de graphe a utilise {network_summary.get('algorithm')} et a detecte {network_summary.get('network_count', 0)} reseau(x) connecte(s).",
            "",
            "Anomalies Salariales",
            f"Anomalies basees sur les regles salariales: {salary_summary['rule_based'].get('anomaly_count', 0)}.",
            f"Anomalies statistiques salariales: {salary_summary['statistical'].get('anomaly_count', 0)}.",
            "Les controles par regles salariales sont optionnels et peuvent etre ignores si aucun fichier de regles n'a ete fourni.",
            "",
            "Prochaines Etapes Recommandees",
            "- Examiner d'abord les employes ayant le risque le plus eleve.",
            "- Verifier les comptes bancaires partages et les identifiants dupliques avec les documents sources.",
            "- Enqueter sur les travailleurs fantomes avant l'approbation de la paie.",
            "- Ajouter des regles salariales propres a l'organisation si les controles par regles ont ete ignores.",
            "",
            "Notes sur les Donnees et la Confidentialite",
            "Ce rapport repose sur des statistiques produites par des controles deterministes. Le redacteur IA n'a pas recu de lignes CSV brutes ni de donnees personnelles en masse.",
        ]
        return "\n".join(lines)

    lines = [
        "Executive Summary",
        f"Sentinel Gov reviewed {report_payload['analysis_scope']['total_registry_records']} registry records and {report_payload['analysis_scope']['total_payroll_records']} payroll records.",
        f"{risk_summary.get('employees_with_risk', 0)} employees received at least one risk factor. The highest risk score was {risk_summary.get('highest_risk_score', 0)}.",
        "",
        "Key Findings",
        f"- Duplicate national IDs found: {finding_counts['duplicate_national_ids_found']}",
        f"- Duplicate bank accounts found: {finding_counts['duplicate_bank_accounts_found']}",
        f"- Potential ghost workers found: {finding_counts['potential_ghost_workers']}",
        f"- Fuzzy name matches found: {finding_counts['registry_fuzzy_name_matches_found'] + finding_counts['payroll_fuzzy_name_matches_found']}",
        f"- Fraud networks found: {finding_counts['fraud_networks_found']}",
        "",
        "Risk Distribution",
        f"- None: {risk_summary.get('level_counts', {}).get('None', 0)}",
        f"- Low: {risk_summary.get('level_counts', {}).get('Low', 0)}",
        f"- Moderate: {risk_summary.get('level_counts', {}).get('Moderate', 0)}",
        f"- High: {risk_summary.get('level_counts', {}).get('High', 0)}",
        f"- Critical: {risk_summary.get('level_counts', {}).get('Critical', 0)}",
        "",
        "Fraud Networks",
        f"The graph analysis used {network_summary.get('algorithm')} and found {network_summary.get('network_count', 0)} connected network(s).",
        "",
        "Salary Anomalies",
        f"Rule-based salary anomalies: {salary_summary['rule_based'].get('anomaly_count', 0)}.",
        f"Statistical salary anomalies: {salary_summary['statistical'].get('anomaly_count', 0)}.",
        "",
        "Recommended Next Steps",
        "- Review the highest-risk employees first.",
        "- Validate shared bank account and duplicate ID findings against source documents.",
        "- Investigate ghost workers before payroll approval.",
        "- Add organization-specific salary rules if rule-based salary checks were skipped.",
        "",
        "Data And Privacy Notes",
        "This report is based on summary statistics generated by deterministic checks. The AI report writer did not receive raw CSV rows or bulk PII.",
    ]
    return "\n".join(lines)

def generate_ai_report(report_payload: dict, language: str = DEFAULT_REPORT_LANGUAGE) -> dict:
    language = normalize_report_language(language)
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    fallback_text = build_local_report(report_payload, language)

    if not api_key:
        return {
            "enabled": False,
            "provider": "local_fallback",
            "reason": "No GEMINI_API_KEY or GOOGLE_API_KEY was found in the environment.",
            "model": None,
            "language": language,
            "text": fallback_text,
        }

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=build_report_prompt(report_payload, language),
            config={
                "temperature": 0.2,
            },
        )
        report_text = getattr(response, "text", "") or fallback_text

        return {
            "enabled": True,
            "provider": "gemini",
            "model": GEMINI_MODEL,
            "language": language,
            "text": report_text,
        }
    except Exception as exc:
        return {
            "enabled": False,
            "provider": "local_fallback",
            "reason": f"Gemini report generation failed: {type(exc).__name__}",
            "model": GEMINI_MODEL,
            "language": language,
            "text": fallback_text,
        }

def build_report_payload_from_results(results: dict) -> dict:
    return build_report_payload(
        results["stats"],
        results["exact_match_findings"],
        results["fuzzy_name_findings"],
        results["ghost_workers"],
        results["salary_anomaly_findings"],
        results["fraud_network_findings"],
        results["risk_score_findings"],
        results.get("financial_exposure", {}),
    )

def get_completed_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        if job["status"] == "failed":
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "Job failed",
                    "step": job.get("step"),
                    "error_type": job.get("error_type"),
                    "error": job.get("error"),
                },
            )
        raise HTTPException(
            status_code=400,
            detail=f"Job is currently {job['status']}",
        )
    return job

def process_payroll_data(
    job_id: str,
    registry_path: str,
    payroll_path: str,
    salary_rules_path: Optional[str] = None,
):
    try:
        jobs[job_id].update({
            "status": "processing",
            "step": "data_ingestion",
            "error": None,
            "error_type": None,
        })
        
        # Step 1: Data ingestion, normalization, and schema validation.
        registry_df = read_and_normalize_csv(registry_path)
        payroll_df = read_and_normalize_csv(payroll_path)
        salary_rules_df = None
        if salary_rules_path:
            salary_rules_df = read_salary_rules_csv(salary_rules_path)

        validate_required_columns(registry_df, REGISTRY_REQUIRED_COLUMNS, "Registry CSV")
        validate_required_columns(payroll_df, PAYROLL_REQUIRED_COLUMNS, "Payroll CSV")

        # Step 2: Exact-match detection.
        jobs[job_id]["step"] = "exact_match_detection"
        duplicate_checks = {
            "registry_duplicate_national_ids": find_duplicate_records(
                registry_df,
                "national_id",
                REGISTRY_FRONTEND_COLUMNS,
            ),
            "registry_duplicate_matricules": find_duplicate_records(
                registry_df,
                "matricule",
                REGISTRY_FRONTEND_COLUMNS,
            ),
            "payroll_duplicate_bank_accounts": find_duplicate_records(
                payroll_df,
                "bank_account",
                PAYROLL_FRONTEND_COLUMNS,
            ),
            "payroll_duplicate_matricules": find_duplicate_records(
                payroll_df,
                "matricule",
                PAYROLL_FRONTEND_COLUMNS,
            ),
        }

        # Step 3: Blocked fuzzy name matching.
        jobs[job_id]["step"] = "fuzzy_name_matching"
        fuzzy_name_checks = {
            "registry_fuzzy_name_matches": find_blocked_fuzzy_name_matches(
                registry_df,
                "full_name",
                REGISTRY_FRONTEND_COLUMNS,
            ),
            "payroll_fuzzy_name_matches": find_blocked_fuzzy_name_matches(
                payroll_df,
                "employee_name",
                PAYROLL_FRONTEND_COLUMNS,
            ),
        }

        # Step 4: Missing-Record Detection (Ghost Workers)
        jobs[job_id]["step"] = "ghost_worker_detection"
        ghost_worker_findings = find_ghost_workers(registry_df, payroll_df)

        # Step 5: Salary anomaly detection.
        jobs[job_id]["step"] = "salary_anomaly_detection"
        salary_anomaly_findings = detect_salary_anomalies(
            registry_df,
            payroll_df,
            salary_rules_df,
        )

        # Step 6: Fraud network construction.
        jobs[job_id]["step"] = "fraud_network_construction"
        fraud_network_findings = build_fraud_networks(
            registry_df,
            payroll_df,
            fuzzy_name_checks,
        )

        # Step 7: Risk scoring engine.
        jobs[job_id]["step"] = "risk_scoring"
        risk_score_findings = calculate_risk_scores(
            registry_df,
            payroll_df,
            duplicate_checks,
            fuzzy_name_checks,
            ghost_worker_findings,
            salary_anomaly_findings,
            fraud_network_findings,
        )

        financial_exposure = calculate_financial_exposure(ghost_worker_findings, salary_anomaly_findings)

        jobs[job_id]["step"] = "building_response"
        stats = {
            "total_registry_records": len(registry_df),
            "total_payroll_records": len(payroll_df),
            "duplicate_national_ids_found": duplicate_checks["registry_duplicate_national_ids"]["duplicate_value_count"],
            "duplicate_bank_accounts_found": duplicate_checks["payroll_duplicate_bank_accounts"]["duplicate_value_count"],
            "duplicate_registry_matricules_found": duplicate_checks["registry_duplicate_matricules"]["duplicate_value_count"],
            "duplicate_payroll_matricules_found": duplicate_checks["payroll_duplicate_matricules"]["duplicate_value_count"],
            "registry_fuzzy_name_matches_found": fuzzy_name_checks["registry_fuzzy_name_matches"]["match_count"],
            "payroll_fuzzy_name_matches_found": fuzzy_name_checks["payroll_fuzzy_name_matches"]["match_count"],
            "potential_ghost_workers": ghost_worker_findings["ghost_worker_count"],
            "salary_rule_anomalies_found": salary_anomaly_findings["rule_based"]["anomaly_count"],
            "salary_statistical_anomalies_found": salary_anomaly_findings["statistical"]["anomaly_count"],
            "fraud_networks_found": fraud_network_findings["network_count"],
            "employees_with_risk": risk_score_findings["summary"]["employees_with_risk"],
            "highest_risk_score": risk_score_findings["summary"]["highest_risk_score"],
            "estimated_financial_exposure": financial_exposure["estimated_total"],
        }

        jobs[job_id]["status"] = "completed"
        jobs[job_id]["step"] = "completed"
        jobs[job_id]["ai_summary_status"] = "not_requested"
        jobs[job_id]["ai_summary_status_by_language"] = {
            language: "not_requested"
            for language in SUPPORTED_REPORT_LANGUAGES
        }
        jobs[job_id]["ai_reports"] = {}
        jobs[job_id]["results"] = {
            "message": "Analysis completed",
            "stats": stats,
            "source_data": {
                "registry_columns": REGISTRY_FRONTEND_COLUMNS,
                "payroll_columns": PAYROLL_FRONTEND_COLUMNS,
                "registry_records": dataframe_records(registry_df, REGISTRY_FRONTEND_COLUMNS),
                "payroll_records": dataframe_records(payroll_df, PAYROLL_FRONTEND_COLUMNS),
            },
            "exact_match_findings": duplicate_checks,
            "fuzzy_name_findings": fuzzy_name_checks,
            "ghost_workers": ghost_worker_findings,
            "salary_anomaly_findings": salary_anomaly_findings,
            "fraud_network_findings": fraud_network_findings,
            "financial_exposure": financial_exposure,
            "risk_score_findings": risk_score_findings,
            "ai_summary": build_ai_summary_marker(job_id, jobs[job_id]),
        }
    except Exception as e:
        jobs[job_id]["status"] = "failed"
        jobs[job_id]["error_type"] = type(e).__name__
        jobs[job_id]["error"] = str(e) or repr(e)

@app.post("/api/upload")
async def upload_files(
    background_tasks: BackgroundTasks,
    registry_file: UploadFile = File(...),
    payroll_file: UploadFile = File(...),
    salary_rules_file: Optional[UploadFile] = File(None),
):
    job_id = str(uuid.uuid4())
    
    # Save files to a temporary location (for demo purposes)
    registry_path = f"tmp_registry_{job_id}.csv"
    payroll_path = f"tmp_payroll_{job_id}.csv"
    salary_rules_path = None
    
    with open(registry_path, "wb") as f:
        f.write(await registry_file.read())
    with open(payroll_path, "wb") as f:
        f.write(await payroll_file.read())

    if salary_rules_file and salary_rules_file.filename:
        salary_rules_path = f"tmp_salary_rules_{job_id}.csv"
        with open(salary_rules_path, "wb") as f:
            f.write(await salary_rules_file.read())

    schema_errors = [
        error
        for error in [
            validate_csv_file_headers(
                registry_path,
                REGISTRY_REQUIRED_COLUMNS,
                "registry_file",
            ),
            validate_csv_file_headers(
                payroll_path,
                PAYROLL_REQUIRED_COLUMNS,
                "payroll_file",
            ),
            validate_csv_file_headers(
                salary_rules_path,
                SALARY_RULE_REQUIRED_COLUMNS,
                "salary_rules_file",
            ) if salary_rules_path else None,
        ]
        if error is not None
    ]

    if schema_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "CSV schema validation failed.",
                "errors": schema_errors,
            },
        )
        
    jobs[job_id] = {
        "status": "pending",
        "ai_summary_status": "not_ready",
        "ai_summary_status_by_language": {},
        "ai_reports": {},
        "step": "queued",
    }
    
    background_tasks.add_task(
        process_payroll_data,
        job_id,
        registry_path,
        payroll_path,
        salary_rules_path,
    )
    
    return {
        "job_id": job_id,
        "message": "Processing started",
        "salary_rules_received": salary_rules_path is not None,
    }

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    response = {
        "job_id": job_id,
        "status": job["status"],
        "ai_summary_status": ai_summary_status_for_job(job),
        "ai_summary_status_by_language": job.get("ai_summary_status_by_language", {}),
        "step": job.get("step"),
    }
    if job["status"] == "failed":
        response["error_type"] = job.get("error_type")
        response["error"] = job.get("error")
    return response

@app.get("/api/results/{job_id}")
async def get_results(job_id: str):
    job = get_completed_job(job_id)
    return job["results"]

@app.post("/api/ai-summary/{job_id}")
def create_ai_summary(
    job_id: str,
    force: bool = False,
    language: str = DEFAULT_REPORT_LANGUAGE,
):
    language = normalize_report_language(language)
    job = get_completed_job(job_id)
    ai_reports = job.setdefault("ai_reports", {})
    language_statuses = job.setdefault("ai_summary_status_by_language", {})

    if not ai_reports and job.get("ai_report"):
        legacy_language = normalize_report_language(
            job["ai_report"].get("language", DEFAULT_REPORT_LANGUAGE)
        )
        ai_reports[legacy_language] = job["ai_report"]

    if language in ai_reports and not force:
        language_statuses[language] = "completed"
        job["ai_summary_status"] = ai_summary_status_for_job(job)
        job["results"]["ai_summary"] = build_ai_summary_marker(job_id, job)
        return {
            "job_id": job_id,
            "cached": True,
            "language": language,
            "ai_summary_status": job["ai_summary_status"],
            "supported_languages": sorted(SUPPORTED_REPORT_LANGUAGES.keys()),
            "ai_report": ai_reports[language],
        }

    try:
        job["ai_summary_status"] = "generating"
        language_statuses[language] = "generating"
        job["results"]["ai_summary"] = build_ai_summary_marker(job_id, job)
        report_payload = build_report_payload_from_results(job["results"])
        ai_report = generate_ai_report(report_payload, language)
        ai_reports[language] = ai_report
        job["ai_report"] = ai_report
        language_statuses[language] = "completed"
        job["ai_summary_status"] = ai_summary_status_for_job(job)
        job["results"]["ai_summary"] = build_ai_summary_marker(job_id, job)

        return {
            "job_id": job_id,
            "cached": False,
            "language": language,
            "ai_summary_status": job["ai_summary_status"],
            "supported_languages": sorted(SUPPORTED_REPORT_LANGUAGES.keys()),
            "ai_report": ai_report,
        }
    except Exception as exc:
        language_statuses[language] = "failed"
        job["ai_summary_status"] = ai_summary_status_for_job(job)
        job["results"]["ai_summary"] = build_ai_summary_marker(job_id, job)
        raise HTTPException(
            status_code=500,
            detail={
                "message": "AI summary generation failed.",
                "language": language,
                "error_type": type(exc).__name__,
            },
        )

@app.get("/")
def root():
    return {"message": "Sentinel Gov Backend API is running."}
