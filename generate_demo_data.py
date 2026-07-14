"""
PayrollGuard AI — Demo Dataset Generator
Generates realistic synthetic Cameroonian payroll data at controlled fraud ratios.
Run: python generate_demo_data.py
Outputs: demo_registry.csv, demo_payroll.csv, demo_salary_rules.csv
"""

import pandas as pd
import random
from datetime import datetime, timedelta
import os

random.seed(42)  # Remove this line to get a fresh unique dataset each run

# ─────────────────────────────────────────────
# CONFIG — tweak these freely
# ─────────────────────────────────────────────
CONFIG = {
    "total_registry": 10000,
    "clean_matches": 9000,
    "ghost_workers": 300,
    "duplicate_nic_pairs": 200,
    "shared_bank_pairs": 300,
    "fuzzy_name_pairs": 250,
    "salary_anomalies": 200,
    "fraud_network_clusters": 35,
    "payment_date": "2026-06-30",
    "salary_rule_tolerance": 0.20,
}

# ─────────────────────────────────────────────
# REFERENCE DATA (realistic Cameroonian context)
# ─────────────────────────────────────────────

CAMEROONIAN_FIRST_NAMES = [
    # Francophone Centre / Sud / Est
    "Jean", "Marie", "Paul", "Cécile", "Emmanuel", "Françoise", "Pierre",
    "Agnès", "Claude", "Monique", "Samuel", "Brigitte", "Albert", "Justine",
    "Roger", "Véronique", "Alain", "Sylvie", "Richard", "Nathalie", "Henri",
    "Bernadette", "Joseph", "Thérèse", "Martin", "Astrid", "Victor", "Sandrine",
    "André", "Isabelle", "Rodrigue", "Chanceline", "Boris", "Carine", "Didier",
    "Ghislaine", "Edmond", "Laetitia", "Faustin", "Nadège", "Gervais", "Solange",
    "Hervé", "Claudette", "Léonard", "Micheline", "Patrice", "Rosalie", "Serge",
    "Valentine", "Stéphane", "Yvonne", "Thierry", "Aurore", "Bertrand", "Arlette",
    "Jude", "Vanessa", "Martial", "Joëlle", "Florent", "Charline", "Gustave",
    "Patience", "Anicet", "Gaëlle", "Romuald", "Florette", "Désiré", "Ariane"
]

CAMEROONIAN_SURNAMES = [
    # Centre / Sud / Est (Beti, Bulu, Fang)
    "Mbarga", "Tabe", "Nkomo", "Ewondo", "Fouda", "Abena", "Ngoua",
    "Essomba", "Mendo", "Ondoa", "Mba", "Bikele", "Nyamsi", "Etoundi",
    "Owona", "Ateba", "Mvondo", "Ndi", "Samba", "Mbele",
    "Bikoo", "Nkoa", "Ayissi", "Mengue", "Obame", "Mintya", "Ondo",
    "Bekono", "Mvogo", "Meyong", "Mbock", "Ekane", "Effa", "Ewane",
    "Ndongo", "Edjenguele", "Akono", "Belinga", "Bitang", "Nkal", "Tsimi",
    "Yombi", "Beyala", "Eteme", "Mezo", "Manga", "Ngono", "Djomo",
    "Zang", "Zambo", "Zogo", "Zoa", "Zinkou", "Zoa", "Ndoumbe",
    "Abomo", "Abessolo", "Abanda", "Assamba", "Atangana", "Azombo",
    "Bengono", "Binyom", "Ebolo", "Edou", "Ekomo", "Eloundou",
    "Engonga", "Engoung", "Eto", "Etoga", "Evina", "Eyinga",
    "Medza", "Mekoue", "Menye", "Meye", "Mezui", "Minkoa",
    "Minso", "Minyem", "Misso", "Mitogo", "Mvoe", "Mvouto",
    # Littoral / Bassa / Douala
    "Ngando", "Nkoulou", "Mbouda", "Ngaha", "Mbita", "Nsom", "Biwole",
    "Ngassa", "Nzekwe", "Tezanou", "Kuate", "Feugang",
    "Dissake", "Doumbe", "Eboumbou", "Ekwalla", "Epee", "Essome",
    "Libom", "Lipem", "Loe", "Loga", "Longo", "Mabou",
    "Makongo", "Malah", "Malobe", "Manyaka", "Mapeke", "Matomb",
    # Bamileke / Ouest
    "Tchinda", "Kamga", "Kouam", "Nkeng", "Fotso", "Tchiaze", "Fopa",
    "Nguimkeu", "Tchoupo", "Wamba", "Nana", "Talla", "Fomba", "Feudjio",
    "Kengne", "Kenfack", "Kepmegni", "Kepseu", "Ketchemen", "Keutcha",
    "Kouakap", "Kouatcho", "Kougang", "Kougmo", "Kouna", "Kounkou",
    "Lontsi", "Lontsie", "Louokap", "Louomou", "Lontchi",
    "Mabou", "Mache", "Maffo", "Magne", "Magni", "Mahop",
    "Nana", "Nanfack", "Nangmo", "Naptchou", "Ndam", "Ndapet",
    "Simo", "Simou", "Siwe", "Siyam", "Sogang", "Sokeng",
    "Tagne", "Tagni", "Takem", "Takouo", "Talom", "Tamgni",
    # Anglophone NW / SW (Grassfields, coastal)
    "Fon", "Njei", "Wung", "Che", "Forba",
    "Mbah", "Nfor", "Wirba", "Tangem",
    "Oben", "Ngong", "Ebai", "Enow", "Arrey",
    "Ayuk", "Besong", "Agbor", "Ojong", "Orock",
    "Ntui", "Akam", "Ashu", "Nkematu",
    "Achu", "Achuo", "Ajih", "Ajong", "Akah", "Akwo",
    "Ambe", "Amungwa", "Anye", "Anyighe", "Atabong", "Ateghang",
    "Azinwi", "Bakia", "Balla", "Bambot", "Bame", "Bantar",
    "Foncha", "Fondoh", "Fongwa", "Forchu", "Forjindam",
    "Ghogomu", "Ghogomou", "Gwanvoma",
    "Leke", "Lum", "Manka", "Mbiydzenyuy", "Mbu",
    "Ndikum", "Ndzi", "Neba", "Nfi", "Ngam",
    "Nkemdirim", "Nkengasong", "Nkongho", "Nkuo",
    "Tabi", "Tabot", "Tafon", "Takang", "Tambe",
    # Northern (Fulani / Arab-Choa / Mandara)
    "Bello", "Hamadou", "Aliou", "Moussa", "Maigari",
    "Bouba", "Garba", "Issa", "Lamine", "Oumarou",
    "Adamu", "Ahmadou", "Alhadji", "Alkali", "Baba",
    "Dairou", "Djibril", "Djiddi", "Djoro",
    "Fadimatou", "Fanta", "Garga", "Harouna",
    "Iya", "Kourgui", "Mahamat", "Malam", "Mallam",
    "Mohamadou", "Mohaman", "Musa",
    "Nana", "Ousman", "Sadou", "Sali", "Sarki",
    "Tchamba", "Tcheroma", "Voundzou", "Yerima",
]

MINISTRIES = [
    "MINEDUB", "MINESEC", "MINSANTE", "MINFI", "MINFOPRA",
    "MINTSS", "MINJUSTICE", "MINADER", "MINEE", "MINTP",
    "MINCOM", "MINCULT", "MINSEP", "MINRESI", "MINPOSTEL"
]

DEPARTMENTS = [
    "Administration Générale", "Ressources Humaines", "Comptabilité",
    "Inspection", "Planification", "Informatique", "Archives",
    "Affaires Juridiques", "Communication", "Logistique",
    "Formation", "Contrôle Interne", "Budget", "Secrétariat Général"
]

GRADES = ["A1", "A2", "B1", "B2", "C1", "C2", "D"]

DUTY_POST_CODES = {
    "A1": "DAI", "A2": "DAII", "B1": "DBI",
    "B2": "DBII", "C1": "DCI", "C2": "DCII", "D": "DD"
}

GRADE_SALARY = {
    "A1": (450000, 650000),
    "A2": (350000, 500000),
    "B1": (280000, 420000),
    "B2": (220000, 350000),
    "C1": (160000, 260000),
    "C2": (130000, 200000),
    "D":  (100000, 160000),
}

ALLOWANCE_OPTIONS = ["housing", "duty", "representation", "transport", "family"]

BANKS = [
    "Afriland First Bank", "SCB Cameroun", "BICEC",
    "UBA Cameroun", "Ecobank Cameroun", "SGBC", "CCA Bank"
]

REGIONS = [
    "Centre", "Littoral", "Ouest", "Nord-Ouest", "Sud-Ouest",
    "Est", "Sud", "Adamaoua", "Nord", "Extrême-Nord"
]

ECHELONS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]

CATEGORY_BY_GRADE = {
    "A1": "A",
    "A2": "A",
    "B1": "B",
    "B2": "B",
    "C1": "C",
    "C2": "C",
    "D": "D",
}

# ─────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────

def make_matricule(n):
    return f"CM{str(n).zfill(6)}"

def make_national_id():
    return str(random.randint(100000000, 999999999))

def make_phone():
    prefix = random.choice(["670", "671", "672", "677", "690", "691", "699", "650", "655"])
    return f"+237{prefix}{random.randint(100000, 999999)}"

def make_bank_account():
    return str(random.randint(1000000000, 9999999999))

def make_hire_date(min_years_ago=1, max_years_ago=20):
    days = random.randint(min_years_ago * 365, max_years_ago * 365)
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

def make_full_name():
    """
    40% chance of a double first name (e.g. Jean Paul Mbarga).
    Multiplies unique combinations well beyond 10k collision risk.
    """
    has_middle = random.random() < 0.4
    if has_middle:
        first = random.choice(CAMEROONIAN_FIRST_NAMES)
        middle = random.choice(CAMEROONIAN_FIRST_NAMES)
        while middle == first:
            middle = random.choice(CAMEROONIAN_FIRST_NAMES)
        return f"{first} {middle} {random.choice(CAMEROONIAN_SURNAMES)}"
    return f"{random.choice(CAMEROONIAN_FIRST_NAMES)} {random.choice(CAMEROONIAN_SURNAMES)}"

def compute_total_salary(base, grade):
    n_allowances = random.randint(2, 4)
    chosen = random.sample(ALLOWANCE_OPTIONS, n_allowances)
    allowance_total = int(base * random.uniform(0.25, 0.55))
    return base + allowance_total, ",".join(chosen)

def mutate_name(name):
    """Fuzzy variation of a name — realistic data-entry clerk mistakes."""
    parts = name.split()
    first = parts[0]
    last = parts[-1]
    mutation = random.choice([
        "abbrev_first",
        "abbrev_last",
        "swap_order",
        "typo_last",
        "drop_accent",
        "extra_space",
        "drop_middle",      # Jean Paul Mbarga → Jean Mbarga
        "initial_middle",   # Jean Paul Mbarga → Jean P. Mbarga
    ])
    if mutation == "abbrev_first":
        return f"{first[0]}. {last}"
    elif mutation == "abbrev_last":
        return f"{first} {last[0]}."
    elif mutation == "swap_order":
        return f"{last} {first}"
    elif mutation == "typo_last":
        idx = random.randint(1, len(last) - 1)
        return f"{first} {last[:idx]}{last[idx]}{last[idx:]}"
    elif mutation == "drop_accent":
        replacements = {
            "é": "e", "è": "e", "ê": "e", "ç": "c",
            "à": "a", "â": "a", "î": "i", "ô": "o", "ù": "u"
        }
        mutated = last
        for accented, plain in replacements.items():
            mutated = mutated.replace(accented, plain)
            mutated = mutated.replace(accented.upper(), plain.upper())
        return f"{first} {mutated}"
    elif mutation == "drop_middle":
        # Only meaningful for double-first-name; falls back gracefully
        return f"{first} {last}"
    elif mutation == "initial_middle":
        if len(parts) == 3:
            return f"{first} {parts[1][0]}. {last}"
        return f"{first} {last}"
    else:
        return f"{first}  {last}"


# ─────────────────────────────────────────────
# CORE GENERATOR
# ─────────────────────────────────────────────

def generate():
    print("PayrollGuard AI — Demo Dataset Generator")
    print("=" * 50)

    registry_rows = []
    payroll_rows = []

    used_nics = set()
    used_accounts = set()

    def fresh_nic():
        while True:
            nic = make_national_id()
            if nic not in used_nics:
                used_nics.add(nic)
                return nic

    def fresh_account():
        while True:
            acc = make_bank_account()
            if acc not in used_accounts:
                used_accounts.add(acc)
                return acc

    matricule_counter = 1

    def next_matricule():
        nonlocal matricule_counter
        m = make_matricule(matricule_counter)
        matricule_counter += 1
        return m

    # ── 1. CLEAN WORKERS ────────────────────────────────
    print(f"  Generating {CONFIG['clean_matches']:,} clean matching workers...")
    clean_registry = []
    for _ in range(CONFIG["clean_matches"]):
        mat = next_matricule()
        name = make_full_name()
        nic = fresh_nic()
        grade = random.choice(GRADES)
        base_salary = random.randint(*GRADE_SALARY[grade])
        total_salary, allowances = compute_total_salary(base_salary, grade)
        ministry = random.choice(MINISTRIES)
        department = random.choice(DEPARTMENTS)
        bank = random.choice(BANKS)
        account = fresh_account()
        location = random.choice(REGIONS)
        hire_date = make_hire_date()

        reg_row = {
            "matricule": mat, "full_name": name, "national_id": nic,
            "phone": make_phone(), "ministry": ministry, "department": department,
            "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
            "category": random.choice(["A", "B", "C"]),
            "class_echelon": random.choice(ECHELONS),
            "hire_date": hire_date, "location": location
        }
        pay_row = {
            "matricule": mat, "employee_name": name, "base_salary": base_salary,
            "allowance_codes": allowances, "total_salary": total_salary,
            "bank_name": bank, "bank_account": account,
            "payment_date": CONFIG["payment_date"]
        }
        clean_registry.append(reg_row)
        payroll_rows.append(pay_row)
        registry_rows.append(reg_row)

    # ── 2. REGISTRY-ONLY WORKERS (on leave / inactive) ──
    remaining_registry = CONFIG["total_registry"] - CONFIG["clean_matches"]
    print(f"  Generating {remaining_registry:,} registry-only workers...")
    for _ in range(remaining_registry):
        mat = next_matricule()
        grade = random.choice(GRADES)
        reg_row = {
            "matricule": mat, "full_name": make_full_name(),
            "national_id": fresh_nic(), "phone": make_phone(),
            "ministry": random.choice(MINISTRIES),
            "department": random.choice(DEPARTMENTS),
            "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
            "category": random.choice(["A", "B", "C"]),
            "class_echelon": random.choice(ECHELONS),
            "hire_date": make_hire_date(), "location": random.choice(REGIONS)
        }
        registry_rows.append(reg_row)

    # ── 3. GHOST WORKERS ────────────────────────────────
    print(f"  Injecting {CONFIG['ghost_workers']:,} ghost workers...")
    for i in range(CONFIG["ghost_workers"]):
        ghost_mat = f"GH{str(i+1).zfill(5)}"
        grade = random.choice(["B1", "B2", "C1", "C2"])
        base = random.randint(*GRADE_SALARY[grade])
        total, allowances = compute_total_salary(base, grade)
        payroll_rows.append({
            "matricule": ghost_mat,
            "employee_name": make_full_name(),
            "base_salary": base,
            "allowance_codes": allowances,
            "total_salary": total,
            "bank_name": random.choice(BANKS),
            "bank_account": fresh_account(),
            "payment_date": CONFIG["payment_date"]
        })

    # ── 4. DUPLICATE NATIONAL ID CASES ──────────────────
    print(f"  Injecting {CONFIG['duplicate_nic_pairs']:,} duplicate national ID cases...")
    clean_sample = random.sample(clean_registry, CONFIG["duplicate_nic_pairs"])
    for original in clean_sample:
        mat = next_matricule()
        grade = random.choice(GRADES)
        dup_reg = {
            "matricule": mat,
            "full_name": make_full_name(),
            "national_id": original["national_id"],  # cloned NIC
            "phone": make_phone(),
            "ministry": random.choice(MINISTRIES),
            "department": random.choice(DEPARTMENTS),
            "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
            "category": random.choice(["A", "B", "C"]),
            "class_echelon": random.choice(ECHELONS),
            "hire_date": make_hire_date(), "location": random.choice(REGIONS)
        }
        base = random.randint(*GRADE_SALARY[grade])
        total, allowances = compute_total_salary(base, grade)
        registry_rows.append(dup_reg)
        payroll_rows.append({
            "matricule": mat, "employee_name": dup_reg["full_name"],
            "base_salary": base, "allowance_codes": allowances,
            "total_salary": total, "bank_name": random.choice(BANKS),
            "bank_account": fresh_account(),
            "payment_date": CONFIG["payment_date"]
        })

    # ── 5. SHARED BANK ACCOUNT CASES ────────────────────
    print(f"  Injecting {CONFIG['shared_bank_pairs']:,} shared bank account cases...")
    # Build index for O(1) lookup — critical at 10k scale
    payroll_index = {p["matricule"]: p for p in payroll_rows}

    shared_accounts_injected = []
    bank_sample = random.sample(clean_registry, CONFIG["shared_bank_pairs"])
    for original in bank_sample:
        shared_acc = fresh_account()
        shared_bank = random.choice(BANKS)
        shared_accounts_injected.append(shared_acc)
        ghost_mat = f"SB{len(shared_accounts_injected):04d}"
        grade = random.choice(GRADES)
        base = random.randint(*GRADE_SALARY[grade])
        total, allowances = compute_total_salary(base, grade)

        # Patch original payroll row via index — O(1)
        if original["matricule"] in payroll_index:
            payroll_index[original["matricule"]]["bank_account"] = shared_acc
            payroll_index[original["matricule"]]["bank_name"] = shared_bank

        new_reg = {
            "matricule": ghost_mat, "full_name": make_full_name(),
            "national_id": fresh_nic(), "phone": make_phone(),
            "ministry": original["ministry"],
            "department": random.choice(DEPARTMENTS),
            "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
            "category": random.choice(["A", "B", "C"]),
            "class_echelon": random.choice(ECHELONS),
            "hire_date": make_hire_date(), "location": random.choice(REGIONS)
        }
        new_pay = {
            "matricule": ghost_mat, "employee_name": new_reg["full_name"],
            "base_salary": base, "allowance_codes": allowances,
            "total_salary": total, "bank_name": shared_bank,
            "bank_account": shared_acc,
            "payment_date": CONFIG["payment_date"]
        }
        registry_rows.append(new_reg)
        payroll_rows.append(new_pay)
        payroll_index[ghost_mat] = new_pay

    # ── 6. FUZZY NAME CASES ─────────────────────────────
    print(f"  Injecting {CONFIG['fuzzy_name_pairs']:,} fuzzy name variations...")
    fuzzy_sample = random.sample(clean_registry, CONFIG["fuzzy_name_pairs"])
    for original in fuzzy_sample:
        mat = next_matricule()
        mutated = mutate_name(original["full_name"])
        grade = random.choice(GRADES)
        base = random.randint(*GRADE_SALARY[grade])
        total, allowances = compute_total_salary(base, grade)
        registry_rows.append({
            "matricule": mat, "full_name": mutated,
            "national_id": fresh_nic(), "phone": make_phone(),
            "ministry": original["ministry"],
            "department": original["department"],
            "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
            "category": random.choice(["A", "B", "C"]),
            "class_echelon": random.choice(ECHELONS),
            "hire_date": make_hire_date(), "location": original["location"]
        })
        payroll_rows.append({
            "matricule": mat, "employee_name": mutated,
            "base_salary": base, "allowance_codes": allowances,
            "total_salary": total, "bank_name": random.choice(BANKS),
            "bank_account": fresh_account(),
            "payment_date": CONFIG["payment_date"]
        })

    # ── 7. SALARY ANOMALIES ──────────────────────────────
    print(f"  Injecting {CONFIG['salary_anomalies']:,} salary anomalies...")
    eligible = [p for p in payroll_rows if not p["matricule"].startswith("GH")]
    anomaly_sample = random.sample(eligible, CONFIG["salary_anomalies"])
    for row in anomaly_sample:
        row["base_salary"] = row["base_salary"] * random.randint(3, 10)
        row["total_salary"] = row["base_salary"] + int(row["base_salary"] * 0.4)

    # ── 8. FRAUD NETWORK CLUSTERS ────────────────────────
    print(f"  Injecting {CONFIG['fraud_network_clusters']} coordinated fraud networks...")
    for cluster_id in range(1, CONFIG["fraud_network_clusters"] + 1):
        cluster_size = random.randint(3, 7)
        shared_account = fresh_account()
        shared_bank = random.choice(BANKS)
        shared_nic = make_national_id()
        ministry = random.choice(MINISTRIES)

        for j in range(cluster_size):
            mat = f"FN{cluster_id:02d}{j:02d}"
            grade = random.choice(["B1", "B2", "C1"])
            base = random.randint(*GRADE_SALARY[grade])
            total, allowances = compute_total_salary(base, grade)
            name = make_full_name()
            nic = shared_nic if j < 2 else fresh_nic()
            account = shared_account
            is_ghost = j >= (cluster_size - 1) and cluster_size > 3

            if not is_ghost:
                registry_rows.append({
                    "matricule": mat, "full_name": name,
                    "national_id": nic, "phone": make_phone(),
                    "ministry": ministry,
                    "department": random.choice(DEPARTMENTS),
                    "grade": grade, "duty_post_code": DUTY_POST_CODES[grade],
                    "category": random.choice(["A", "B", "C"]),
                    "class_echelon": random.choice(ECHELONS),
                    "hire_date": make_hire_date(min_years_ago=0, max_years_ago=2),
                    "location": random.choice(REGIONS)
                })

            payroll_rows.append({
                "matricule": mat, "employee_name": name,
                "base_salary": base, "allowance_codes": allowances,
                "total_salary": total, "bank_name": shared_bank,
                "bank_account": account,
                "payment_date": CONFIG["payment_date"]
            })

    # ─────────────────────────────────────────────
    # EXPORT
    # ─────────────────────────────────────────────
    df_registry = pd.DataFrame(registry_rows).drop_duplicates(subset=["matricule"])
    df_payroll = pd.DataFrame(payroll_rows).drop_duplicates(subset=["matricule"])

    df_registry = df_registry.sample(frac=1, random_state=42).reset_index(drop=True)
    df_payroll = df_payroll.sample(frac=1, random_state=42).reset_index(drop=True)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    registry_path = os.path.join(out_dir, "demo_registry.csv")
    payroll_path = os.path.join(out_dir, "demo_payroll.csv")

    df_registry.to_csv(registry_path, index=False)
    df_payroll.to_csv(payroll_path, index=False)

    # ─────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────
    total_first = len(CAMEROONIAN_FIRST_NAMES)
    total_last = len(CAMEROONIAN_SURNAMES)
    print("\n" + "=" * 50)
    print("Dataset generated successfully!")
    print(f"   Registry:       {len(df_registry):,} records -> demo_registry.csv")
    print(f"   Payroll:        {len(df_payroll):,} records -> demo_payroll.csv")
    print(f"   Name pool:      {total_first} first x {total_last} surnames")
    print(f"   Max 2-part combinations: {total_first * total_last:,}")
    print(f"   Max 3-part combinations: {total_first * total_first * total_last:,}")
    print()
    print("   Fraud injected:")
    print(f"   Ghost workers:             {CONFIG['ghost_workers']:,}")
    print(f"   Duplicate NIC cases:       {CONFIG['duplicate_nic_pairs']:,}")
    print(f"   Shared bank account cases: {CONFIG['shared_bank_pairs']:,}")
    print(f"   Fuzzy name cases:          {CONFIG['fuzzy_name_pairs']:,}")
    print(f"   Salary anomalies:          {CONFIG['salary_anomalies']:,}")
    print(f"   Fraud network clusters:    {CONFIG['fraud_network_clusters']}")
    print()
    print("   To get a fresh unique dataset: remove random.seed(42) at top of file.")
    print("=" * 50)


if __name__ == "__main__":
    generate()
