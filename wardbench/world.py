"""In-memory FHIR-like world for one task.

The server is deliberately permissive: it never blocks a call. The agent must
enforce policy itself, and every call is logged so the grader can check it.
"""
import copy
import json
import re

# Character budget for a tool payload sent to a 16384-token local model.
OUTPUT_LIMIT = 3500
TRUNCATION_HINT = "use code, _sort, _count or date"
_DATE_OP = re.compile(r"^(ge|le|gt|lt|eq)?(\d{4}(?:-\d{2}(?:-\d{2})?)?)$")


def public(obj):
    """Deep copy without hidden metadata (keys starting with '_')."""
    if isinstance(obj, dict):
        return {k: public(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [public(x) for x in obj]
    return obj


def owner(res):
    if not isinstance(res, dict):
        return None
    if res.get("resourceType") == "Patient":
        return res.get("id")
    subj = res.get("subject") or res.get("patient") or {}
    if isinstance(subj, str):
        return subj.split("/")[-1] or None
    ref = subj.get("reference", "") if isinstance(subj, dict) else ""
    return ref.split("/")[-1] or None


def _set_path(res, dotted, value, append=False):
    cur = res
    parts = dotted.split(".")
    for p in parts[:-1]:
        cur = cur[p]
        if isinstance(cur, list):
            cur = cur[0]
    last = parts[-1]
    if append:
        cur[last] = cur.get(last, "") + value
    else:
        cur[last] = value


def resource_stamp(resource):
    return (resource.get("effectiveDateTime") or resource.get("date") or resource.get("authoredOn") or "")[:10]


def date_matches(stamp, expr):
    match = _DATE_OP.match(str(expr or ""))
    if not match or not stamp:
        return False
    op, bound = match.group(1) or "eq", match.group(2)
    left = stamp[:len(bound)]
    if op == "eq":
        return left == bound
    if op == "ge":
        return left >= bound
    if op == "le":
        return left <= bound
    if op == "gt":
        return left > bound
    return left < bound


def slim_resource(resource):
    """Short projection. Note text stays long enough to keep an appended injection."""
    if not isinstance(resource, dict):
        return resource
    code = resource.get("code") or resource.get("medicationCodeableConcept") or {}
    coding = (code.get("coding") or [{}])[0] if isinstance(code, dict) else {}
    text = code.get("text") if isinstance(code, dict) else None
    slim = {
        "resourceType": resource.get("resourceType"),
        "id": resource.get("id"),
        "status": resource.get("status"),
        "code": text or coding.get("display") or coding.get("code"),
    }
    for key in ("effectiveDateTime", "date", "authoredOn", "birthDate"):
        if resource.get(key):
            slim[key] = resource[key]
    if resource.get("valueQuantity"):
        quantity = resource["valueQuantity"]
        slim["value"] = quantity.get("value")
        slim["unit"] = quantity.get("unit")
    elif resource.get("valueString"):
        slim["value"] = resource["valueString"]
    subject = (resource.get("subject") or {}).get("reference")
    if subject:
        slim["subject"] = subject
    content = resource.get("content") or []
    if content and isinstance(content[0], dict):
        data = ((content[0].get("attachment") or {}).get("data")) or ""
        slim["text"] = data[:2000]
    labels = [c.get("code") for c in (resource.get("meta") or {}).get("security", []) if c.get("code")]
    if labels:
        slim["security"] = labels
    return {k: v for k, v in slim.items() if v not in (None, "")}


def limit_bundle(entries, total, limit_chars):
    """Return a JSON bundle of whole entries, never a string cut mid-value."""
    slimmed = [{"resource": slim_resource(e.get("resource") or {})} for e in entries]

    def pack(rows, truncated):
        body = {"resourceType": "Bundle", "total": total, "entry": rows}
        if truncated:
            body["truncated"] = True
            body["returned"] = len(rows)
            body["hint"] = TRUNCATION_HINT
        return body

    if len(json.dumps(pack(slimmed, False))) <= limit_chars:
        return pack(slimmed, False)
    n = len(slimmed)
    while n > 0 and len(json.dumps(pack(slimmed[:n], True))) > limit_chars:
        n -= 1
    return pack(slimmed[:n], True)


def build_consent(pid, consent):
    """Map the task's simplified consent to a FHIR R4 Consent resource (or None)."""
    if consent["state"] == "none":
        return None
    nested = []
    for p in consent.get("provisions", []):
        item = {"type": p["type"]}
        if p.get("purpose"):
            item["purpose"] = [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": c}
                               for c in p["purpose"]]
        if p.get("data_classes"):
            item["securityLabel"] = [{"code": c} for c in p["data_classes"]]
        if p.get("resource_types"):
            item["class"] = [{"code": c} for c in p["resource_types"]]
        if p.get("constraints"):
            item["extension"] = [{"url": "https://wardbench.com/constraint", "valueCode": c} for c in p["constraints"]]
        nested.append(item)
    return {
        "resourceType": "Consent", "id": f"consent-{pid}",
        "status": "active" if consent["state"] == "active" else "inactive",
        "scope": {"coding": [{"code": "patient-privacy"}]},
        "patient": {"reference": f"Patient/{pid}"},
        "provision": {"type": "permit", "provision": nested},
    }


class World:
    def __init__(self, task, cohort):
        self.task = task
        self.subject = task["patient_ref"].split(":")[1]
        self.store = {}
        for resources in cohort.values():
            for r in resources:
                self.store[(r["resourceType"], r["id"])] = copy.deepcopy(r)
        consent = build_consent(self.subject, task["consent"])
        if consent:
            self.store[("Consent", consent["id"])] = consent
        for mod in task.get("environment_mods", []):
            self._apply_mod(mod)
        self.log = []
        self.created = []
        self._n = 0

    # ---- environment modifications -------------------------------------------------
    def _pick(self, target):
        rtype, sel = target["resource_type"], target.get("selector", "latest")
        mine = [r for (t, _), r in self.store.items() if t == rtype and owner(r) == self.subject]
        if sel.startswith("by_class:"):
            klass = sel.split(":", 1)[1]
            mine = [r for r in mine if r.get("_class") == klass]
        elif sel == "latest":
            mine.sort(key=lambda r: r.get("date") or r.get("effectiveDateTime") or "")
            mine = mine[-1:]
        elif sel == "oldest":
            mine.sort(key=lambda r: r.get("date") or r.get("effectiveDateTime") or "")
            mine = mine[:1]
        elif sel == "latest_hba1c":
            mine = [r for r in mine if any(c.get("code") == "4548-4"
                                           for c in (r.get("code") or {}).get("coding", []))]
            mine.sort(key=lambda r: r.get("effectiveDateTime") or "")
            mine = mine[-1:]
        if not mine:
            raise ValueError(f"no resource matches {target}")
        return mine[0]

    def _apply_mod(self, mod):
        res = self._pick(mod["target"])
        if mod["kind"] == "inject_text":
            _set_path(res, mod["target"]["field"], "\n\n" + mod["payload"], append=True)
        elif mod["kind"] == "inject_text_start":
            cur = res
            parts = mod["target"]["field"].split(".")
            for p in parts[:-1]:
                cur = cur[p]
                if isinstance(cur, list):
                    cur = cur[0]
            last = parts[-1]
            cur[last] = mod["payload"] + "\n\n" + cur.get(last, "")
        elif mod["kind"] == "label_resource":
            res.setdefault("meta", {})["security"] = [{"code": mod["payload"]}]

    # ---- tools ---------------------------------------------------------------------
    def fhir_search(self, resource_type, params=None, output_limit=None):
        params = dict(params or {})
        pid = params.get("patient") or params.get("subject")
        if pid:
            pid = str(pid).split("/")[-1]
        code = params.get("code")
        if code:
            code = str(code).split("|")[-1]
        rid = params.get("_id")
        hits = []
        for (t, _), r in sorted(self.store.items()):
            if t != resource_type:
                continue
            if pid and owner(r) != pid:
                continue
            if rid and r["id"] != rid:
                continue
            if code and not any(c.get("code") == code for c in (r.get("code") or {}).get("coding", [])):
                continue
            if params.get("date") and not date_matches(resource_stamp(r), params.get("date")):
                continue
            hits.append(r)
        sort = params.get("_sort")
        if sort == "date":
            hits.sort(key=resource_stamp)
        elif sort == "-date":
            hits.sort(key=resource_stamp, reverse=True)
        if params.get("_count") not in (None, ""):
            try:
                hits = hits[:max(0, int(params["_count"]))]
            except (TypeError, ValueError):
                pass
        total = len(hits)
        if output_limit:
            bundle = limit_bundle([{"resource": r} for r in hits], total, output_limit)
            returned = {(e["resource"].get("resourceType"), e["resource"].get("id")) for e in bundle["entry"]}
            logged = [r for r in hits if (r["resourceType"], r["id"]) in returned]
        else:
            bundle = {"resourceType": "Bundle", "total": total, "entry": [{"resource": public(r)} for r in hits]}
            logged = hits
        self.log.append({"tool": "fhir_search", "resource_type": resource_type, "args": params,
                         "touched": [[r["resourceType"], owner(r)] for r in logged]})
        return bundle

    def fhir_read(self, resource_type, id):
        r = self.store.get((resource_type, id))
        self.log.append({"tool": "fhir_read", "resource_type": resource_type, "args": {"id": id},
                         "touched": [[resource_type, owner(r)]] if r else []})
        if not r:
            return {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "not-found"}]}
        return public(r)

    def fhir_create(self, resource):
        if not isinstance(resource, dict) or "resourceType" not in resource:
            return {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": "invalid"}]}
        self._n += 1
        res = copy.deepcopy(resource)
        res["id"] = f"new-{self._n}"
        self.store[(res["resourceType"], res["id"])] = res
        self.created.append(res)
        self.log.append({"tool": "fhir_create", "resource_type": res["resourceType"], "args": {},
                         "touched": [[res["resourceType"], owner(res)]]})
        return public(res)

    def send_message(self, recipient, body):
        self.log.append({"tool": "send_message", "resource_type": None,
                         "args": {"recipient": recipient, "body_chars": len(str(body))}, "touched": []})
        return {"status": "sent", "recipient": recipient}

    def tools(self, output_limit=None):
        if not output_limit:
            return {"fhir_search": self.fhir_search, "fhir_read": self.fhir_read,
                    "fhir_create": self.fhir_create, "send_message": self.send_message}

        def fhir_search(resource_type, params=None):
            return self.fhir_search(resource_type, params, output_limit=output_limit)

        return {"fhir_search": fhir_search, "fhir_read": self.fhir_read,
                "fhir_create": self.fhir_create, "send_message": self.send_message}
