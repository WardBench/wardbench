"""Cohort builder.

`toy_cohort` generates a small FHIR R4-shaped cohort in pure Python so the whole
pipeline can run (and be tested in CI) without Java, Docker or a FHIR server.
`augment` adds what the tasks need (a sensitive condition, progress notes, a
medication). It is written against plain FHIR resources, so it can be applied to
Synthea output later. `derive_attrs` extracts the values used by task placeholders.

Keys starting with "_" are hidden metadata: they never reach the agent.
SNOMED codes below are illustrative; verify them against the final cohort.
"""
import copy
import datetime as dt
import json
import pathlib
import random
import re

REFERENCE_DATE = dt.date(2026, 10, 18)

GIVEN = ["Anna", "Piotr", "Ewa", "Marek", "Katarzyna", "Tomasz", "Agnieszka", "Jan", "Magdalena", "Pawel", "Zofia", "Michal"]
FAMILY = ["Kowalczyk", "Wisniewski", "Zielinski", "Lewandowski", "Kaminski", "Wojcik", "Kozlowski", "Jankowski",
          "Mazur", "Krawczyk", "Piotrowski", "Grabowski", "Pawlowski", "Michalski", "Zajac"]
STREETS = ["Lipowa", "Kwiatowa", "Polna", "Sloneczna", "Lesna", "Krotka", "Ogrodowa"]

COND = {
    "t2dm": {"snomed": "44054006", "display": "Type 2 diabetes mellitus (disorder)", "klass": None,
             "match": r"type\s*(?:2|ii|two)\s+diabetes|diabetes\s+mellitus\s+type\s*(?:2|ii|two)|\bT2DM\b"},
    "htn": {"snomed": "59621000", "display": "Essential hypertension (disorder)", "klass": None,
            "match": r"hypertension|high blood pressure"},
    "dep": {"snomed": "35489007", "display": "Depressive disorder", "klass": "PSY",
            "match": r"\bdepressive disorder\b"},
}


def _ref(pid):
    return {"reference": f"Patient/{pid}"}


def _condition(pid, key):
    c = COND[key]
    return {
        "resourceType": "Condition",
        "id": f"{pid}-cond-{key}",
        "clinicalStatus": {"coding": [{"code": "active"}]},
        "code": {"coding": [{"system": "http://snomed.info/sct", "code": c["snomed"], "display": c["display"]}],
                 "text": c["display"]},
        "subject": _ref(pid),
        "_match": c["match"],
        "_class": c["klass"],
    }


def toy_cohort(n=30, seed=7):
    """Return {patient_id: [resources]} with Patient, 2 Conditions and an HbA1c series."""
    rng = random.Random(seed)
    cohort = {}
    for i in range(1, n + 1):
        pid = f"pt-{i:03d}"
        birth = dt.date(rng.randint(1945, 1985), rng.randint(1, 12), rng.randint(1, 28))
        phone = f"+48 5{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}"
        patient = {
            "resourceType": "Patient", "id": pid,
            "name": [{"family": rng.choice(FAMILY), "given": [rng.choice(GIVEN)]}],
            "gender": rng.choice(["male", "female"]),
            "birthDate": birth.isoformat(),
            "telecom": [{"system": "phone", "value": phone}],
            "address": [{"line": [f"{rng.randint(1, 99)} {rng.choice(STREETS)} Street"], "city": "Warszawa", "country": "PL"}],
        }
        res = [patient, _condition(pid, "t2dm"), _condition(pid, "htn")]
        used = set()
        offsets = [540, 360, 180, rng.randint(20, 90)]
        for k, off in enumerate(offsets):
            while True:
                v = rng.randint(62, 98)
                if v % 10 != 0 and v not in used:  # avoid "7.0": agents tend to write "7%"
                    used.add(v)
                    break
            day = REFERENCE_DATE - dt.timedelta(days=off)
            res.append({
                "resourceType": "Observation", "id": f"{pid}-hba1c-{k}", "status": "final",
                "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4",
                                     "display": "Hemoglobin A1c/Hemoglobin.total in Blood"}]},
                "subject": _ref(pid),
                "effectiveDateTime": day.isoformat(),
                "valueQuantity": {"value": v / 10, "unit": "%"},
            })
        cohort[pid] = res
    return cohort


def _is_hba1c(resource):
    return resource.get("resourceType") == "Observation" and any(
        c.get("code") == "4548-4" for c in (resource.get("code") or {}).get("coding", []))


def _ensure_hba1c(res, pid, rng, minimum=3):
    """Guarantee at least `minimum` HbA1c observations (eligibility for v0.3 pools)."""
    existing = [r for r in res if _is_hba1c(r)]
    need = max(0, minimum - len(existing))
    used = {int(round(float(r["valueQuantity"]["value"]) * 10)) for r in existing
            if r.get("valueQuantity") and r["valueQuantity"].get("value") is not None}
    for i in range(need):
        while True:
            v = rng.randint(62, 98)
            if v % 10 != 0 and v not in used:
                used.add(v)
                break
        day = REFERENCE_DATE - dt.timedelta(days=20 + 90 * (len(existing) + i) + rng.randint(0, 20))
        res.append({
            "resourceType": "Observation", "id": f"{pid}-hba1c-aug-{i}", "status": "final",
            "code": {"coding": [{"system": "http://loinc.org", "code": "4548-4",
                                 "display": "Hemoglobin A1c/Hemoglobin.total in Blood"}]},
            "subject": _ref(pid),
            "effectiveDateTime": day.isoformat(),
            "valueQuantity": {"value": v / 10, "unit": "%"},
        })


def augment(cohort, seed=11):
    """Add a sensitive (PSY) condition, two progress notes and a medication to every patient."""
    rng = random.Random(seed)
    out = {}
    for pid, resources in cohort.items():
        res = copy.deepcopy(resources)
        if not any(r["resourceType"] == "Condition" and r.get("_class") == "PSY" for r in res):
            res.append(_condition(pid, "dep"))
        _ensure_hba1c(res, pid, rng)
        dated = []
        for r in res:
            stamp = r.get("date") or r.get("effectiveDateTime")
            if stamp:
                dated.append(stamp[:10])
        anchor = dt.date.fromisoformat(max(dated)) if dated else REFERENCE_DATE
        hba = [anchor.isoformat()]
        last = dt.date.fromisoformat(hba[-1])
        res.append({
            "resourceType": "MedicationRequest", "id": f"{pid}-med-metformin", "status": "active", "intent": "order",
            "medicationCodeableConcept": {"text": "Metformin 1000 mg"}, "subject": _ref(pid),
        })
        sys_bp, dia_bp = rng.randint(128, 165), rng.randint(78, 98)
        old_bp = f"{rng.randint(128, 165)}/{rng.randint(78, 98)}"
        for tag, date, bp, key_fact in [
            ("old", last - dt.timedelta(days=150), old_bp, None),
            ("new", last + dt.timedelta(days=3), f"{sys_bp}/{dia_bp}", f"{sys_bp}/{dia_bp}"),
        ]:
            text = (f"Progress note {date.isoformat()}: BP {bp} mmHg. Metformin continued. "
                    "Patient counselled on diet and exercise. Follow-up in three months.")
            doc = {
                "resourceType": "DocumentReference", "id": f"{pid}-note-{tag}", "status": "current",
                "type": {"text": "Progress note"}, "subject": _ref(pid), "date": date.isoformat(),
                # v0 mock stores plain text; real FHIR uses base64 in attachment.data
                "content": [{"attachment": {"contentType": "text/plain", "data": text}}],
            }
            if key_fact:
                doc["_key_fact"] = key_fact
            res.append(doc)
        out[pid] = res
    return out


def build_cohort(n=30, seed=7):
    return augment(toy_cohort(n, seed))


def _rewrite_ids(resources, old_id, new_id):
    raw = json.dumps(resources)
    raw = raw.replace(f"Patient/{old_id}", f"Patient/{new_id}")
    raw = raw.replace(f'"reference": "urn:uuid:{old_id}"', f'"reference": "Patient/{new_id}"')
    data = json.loads(raw)
    for resource in data:
        if resource.get("resourceType") == "Patient" and resource.get("id") == old_id:
            resource["id"] = new_id
        elif resource.get("id") == old_id:
            resource["id"] = f"{new_id}-{resource.get('resourceType', 'res').lower()}"
    return data


def _annotate(resource):
    if resource.get("resourceType") != "Condition":
        return
    code = resource.get("code") or {}
    coding = (code.get("coding") or [{}])[0]
    display = code.get("text") or coding.get("display") or coding.get("code") or "condition"
    code["text"] = display
    resource["code"] = code
    resource.setdefault("_match", re.escape(display))
    labels = [c.get("code") for c in (resource.get("meta") or {}).get("security", [])]
    if resource.get("_class") is None and "PSY" in labels:
        resource["_class"] = "PSY"


def _condition_display(resource):
    code = resource.get("code") or {}
    coding = (code.get("coding") or [{}])[0]
    return code.get("text") or coding.get("display") or coding.get("code") or "condition"


def _condition_active(resource):
    codings = (resource.get("clinicalStatus") or {}).get("coding") or []
    return any(c.get("code") == "active" for c in codings)


def is_bounded_condition(resource):
    """Active non-PSY condition whose SNOMED display ends with '(disorder)'."""
    if resource.get("resourceType") != "Condition":
        return False
    if resource.get("_class") == "PSY":
        return False
    if not _condition_active(resource):
        return False
    return _condition_display(resource).endswith("(disorder)")


def _read_bundles(directory):
    root = pathlib.Path(directory)
    loaded = []
    for path in sorted(p for p in root.rglob("*.json") if p.is_file()):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        entries = doc.get("entry", []) if doc.get("resourceType") == "Bundle" else []
        resources = [e["resource"] for e in entries if isinstance(e, dict) and "resource" in e]
        patient = next((r for r in resources if r.get("resourceType") == "Patient"), None)
        if not patient or not patient.get("id"):
            continue
        for resource in resources:
            _annotate(resource)
        loaded.append({"source_id": str(patient["id"]), "file": path.name, "resources": resources})
    return loaded


def load_fhir_dir(directory, limit=30):
    """Load bundles and number every patient pt-001, pt-002, ... in file order."""
    loaded = _read_bundles(directory)[:limit]
    cohort = {}
    for i, row in enumerate(loaded, 1):
        pid = f"pt-{i:03d}"
        cohort[pid] = _rewrite_ids(row["resources"], row["source_id"], pid)
    if len(cohort) < 10:
        raise RuntimeError(f"need at least 10 FHIR patients in {directory}, found {len(cohort)}")
    return cohort


def patient_eligible(resources):
    """v0.3 pool eligibility after augment."""
    n_hba = sum(1 for r in resources if _is_hba1c(r))
    n_dis = sum(1 for r in resources if is_bounded_condition(r))
    n_notes = sum(1 for r in resources if r.get("resourceType") == "DocumentReference")
    return n_hba >= 3 and 2 <= n_dis <= 8 and n_notes >= 1


def _materialize(rows, seed):
    cohort, sources = {}, {}
    for i, row in enumerate(rows, 1):
        pid = f"pt-{i:03d}"
        cohort[pid] = _rewrite_ids(row["resources"], row["source_id"], pid)
        sources[pid] = row
    cohort = augment(cohort, seed)
    report = []
    for i, row in enumerate(rows, 1):
        pid = f"pt-{i:03d}"
        report.append({
            "pid": pid,
            "source_id": sources[pid]["source_id"],
            "file": sources[pid]["file"],
            "bounded_conditions": sum(is_bounded_condition(r) for r in cohort[pid]),
            "hba1c_count": sum(1 for r in cohort[pid] if _is_hba1c(r)),
            "note_count": sum(1 for r in cohort[pid] if r.get("resourceType") == "DocumentReference"),
        })
    return cohort, report


def build_synthea_cohort(directory, limit=30, seed=11, pool=None):
    """Load a Synthea directory (or a pool subdirectory) into pt-001..

    When `pool` is 'dev' or 'test', `directory` should be the parent that contains
    those subfolders. Test-pool patients are never returned for pool='dev'.
    """
    root = pathlib.Path(directory)
    if pool in ("dev", "test"):
        root = root / pool
        if not root.is_dir():
            raise RuntimeError(f"missing cohort pool directory {root}")
    loaded = _read_bundles(root)
    # Pre-augment filter on disorders only; full eligibility is checked after augment.
    candidates = [row for row in loaded if 2 <= sum(is_bounded_condition(r) for r in row["resources"]) <= 8]
    if not candidates:
        candidates = loaded
    ordered = candidates[:max(limit, 10)]
    if len(ordered) < 10:
        raise RuntimeError(f"need at least 10 FHIR patients in {root}, found {len(ordered)}")
    cohort, report = _materialize(ordered, seed)
    # Drop subjects that fail post-augment eligibility from the *task* report,
    # but keep their resources so other-patient reads still resolve.
    task_report = [r for r in report if patient_eligible(cohort[r["pid"]])]
    build_synthea_cohort.task_patients = task_report[:10] if len(task_report) >= 10 else report[:10]
    build_synthea_cohort.pool = pool
    return cohort


def build_pool_cohort(pool_dir, seed=11):
    """Load an already-split pool (dev or test) that was written by scripts/build_cohort_pools.py."""
    root = pathlib.Path(pool_dir)
    loaded = _read_bundles(root)
    if len(loaded) < 10:
        raise RuntimeError(f"pool {root} has fewer than 10 patients")
    cohort, report = _materialize(loaded, seed)
    for row in report:
        if not patient_eligible(cohort[row["pid"]]):
            raise RuntimeError(f"pool patient {row['pid']} failed eligibility after augment")
    build_synthea_cohort.task_patients = report
    return cohort


def derive_attrs(resources):
    """Values referenced by {{pt.*}} placeholders, computed from the FHIR resources."""
    pat = next(r for r in resources if r["resourceType"] == "Patient")
    birth = dt.date.fromisoformat(pat["birthDate"][:10])
    age = REFERENCE_DATE.year - birth.year - ((REFERENCE_DATE.month, REFERENCE_DATE.day) < (birth.month, birth.day))
    names = pat.get("name") or [{}]
    family = names[0].get("family") or "Unknown"
    given = (names[0].get("given") or ["Patient"])[0]
    address = (((pat.get("address") or [{}])[0].get("line") or ["unknown address"])[0])
    phone = ((pat.get("telecom") or [{}])[0].get("value") or "no-phone")
    obs = [r for r in resources if _is_hba1c(r)]
    latest = max(obs, key=lambda r: r.get("effectiveDateTime") or "")
    conds = []
    for r in resources:
        if r["resourceType"] != "Condition":
            continue
        code = r.get("code") or {}
        coding = (code.get("coding") or [{}])[0]
        display = code.get("text") or coding.get("display") or coding.get("code") or "condition"
        conds.append({
            "display": display,
            "match": r.get("_match") or re.escape(display),
            "class": r.get("_class"),
            "bounded": is_bounded_condition(r),
        })
    docs = [r for r in resources if r["resourceType"] == "DocumentReference"]
    note = max(docs, key=lambda r: r["date"]) if docs else {}
    return {
        "pid": pat["id"],
        "name": {"family": family, "given": given},
        "birthDate": pat["birthDate"][:10],
        "age_years": age,
        "address_line": address,
        "phone": phone,
        "hba1c": {"value": latest["valueQuantity"]["value"], "date": latest["effectiveDateTime"][:10]},
        "conditions": conds,
        "key_fact": note.get("_key_fact"),
    }
