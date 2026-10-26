#!/usr/bin/env python3
"""Deterministic publication SVG figures for the WardBench preprint (S18).

Reads tracks/wardbench/reports/v0.4/summary_v04.json and saved v0.4 result
JSONs in repos/wardbench/results/v0.4/ to emit three publication-grade SVG
figures (plus PDF companions via Inkscape when installed) into
tracks/wardbench/paper/figures/. No external LLM or GPU calls.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HQ = REPO.parent.parent  # nareyko/
SUMMARY = HQ / "tracks/wardbench/reports/v0.4/summary_v04.json"
OUT_DIR = HQ / "tracks/wardbench/paper/figures"


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    margin = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return (max(0.0, (centre - margin) / den), min(1.0, (centre + margin) / den))


def pct(k: int, n: int) -> float:
    return 100.0 * k / n if n else 0.0


def esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def svg_header(w: int, h: int, title: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">\n'
        f"<title>{esc(title)}</title>\n"
        f'<rect width="100%" height="100%" fill="#ffffff"/>\n'
    )


def svg_footer() -> str:
    return "</svg>\n"


def text(x, y, s, *, size=11, anchor="start", weight="normal", fill="#111"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif" '
        f'font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">'
        f"{esc(s)}</text>\n"
    )


def line(x1, y1, x2, y2, *, stroke="#333", width=1.2, dash=None):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{stroke}" stroke-width="{width}"{dash_attr}/>\n'
    )


def rect(x, y, w, h, *, fill="#ccc", stroke=None, sw=1, rx=0):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    r_attr = f' rx="{rx}"' if rx else ""
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'fill="{fill}"{st}{r_attr}/>\n'
    )


def circle(cx, cy, r, *, fill="#000", stroke="#000", sw=1, opacity=1.0):
    return (
        f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="{sw}" fill-opacity="{opacity}"/>\n'
    )


# ---------------------------------------------------------------------------
# Figure 1 — Pareto frontier
# ---------------------------------------------------------------------------

def fig1_pareto(summary: dict) -> str:
    m14 = summary["modes"]
    mm = summary["multi_model"]
    s13 = summary["s13_biomedical_react_json"]
    s14 = summary["s14_api_norm"]
    s14c = summary["s14c_32b_api_norm_full"]
    s16b = summary["s16b_did_plus_api_norm"]
    s16 = summary["s16_32b_factorial_and_thinking"]["qwen3-32b"]

    # (label, util_k, util_n, viol_k, viol_n, color, marker, dx, dy, anchor)
    points = [
        ("ToolSolver (100%, 0%)", 85, 85, 0, 120, "#0a7a2f", "star", 10, 4, "start"),
        ("ToolSolver enforced (90.6%, 0%)", 77, 85, 0, 120, "#0a7a2f", "diamond", 10, 4, "start"),
        ("OpenBioLLM-8B rec (8.2%, 3.3%)", *s13["openbiollm-8b"]["record"]["utility"], *s13["openbiollm-8b"]["record"]["violation"], "#666666", "circle", 8, -5, "start"),
        ("OpenBioLLM-8B prm (3.5%, 2.5%)", *s13["openbiollm-8b"]["prompt"]["utility"], *s13["openbiollm-8b"]["prompt"]["violation"], "#555555", "square", 8, 11, "start"),
        ("MedGemma-4B rec/prm (14.1%, 16.7%)", *s13["medgemma-4b-it"]["prompt"]["utility"], *s13["medgemma-4b-it"]["prompt"]["violation"], "#8a6500", "square", 9, 12, "start"),
        ("7B-FC record (21.2%, 16.7%)", mm["qwen2.5-7b-fc"]["record"]["utility"]["k"], 85, mm["qwen2.5-7b-fc"]["record"]["violation_rate"]["k"], 120, "#6b4ce6", "circle", 9, -4, "start"),
        ("7B-FC prompt (20.0%, 15.8%)", mm["qwen2.5-7b-fc"]["prompt"]["utility"]["k"], 85, mm["qwen2.5-7b-fc"]["prompt"]["violation_rate"]["k"], 120, "#6b4ce6", "square", -9, 4, "end"),
        ("7B-FC prompt+norm (29.4%, 24.2%)", *s14["qwen2.5-7b-fc_prompt"]["utility"]["norm"], *s14["qwen2.5-7b-fc_prompt"]["violation_rate"]["norm"], "#6b4ce6", "diamond", 9, 4, "start"),
        ("14B record (65.9%, 43.3%)", m14["record"]["utility"]["k"], 85, m14["record"]["violation_rate"]["k"], 120, "#1f6feb", "circle", -9, -6, "end"),
        ("14B prompt (62.4%, 21.7%)", m14["prompt"]["utility"]["k"], 85, m14["prompt"]["violation_rate"]["k"], 120, "#1f6feb", "square", 9, 12, "start"),
        ("14B prompt+norm (65.9%, 17.5%)", *s14["qwen3-14b_prompt"]["utility"]["norm"], *s14["qwen3-14b_prompt"]["violation_rate"]["norm"], "#1f6feb", "diamond", 9, -5, "start"),
        ("14B enforced (68.2%, 4.2%)", m14["enforced"]["utility"]["k"], 85, m14["enforced"]["violation_rate"]["k"], 120, "#1f6feb", "triangle", 9, -4, "start"),
        ("14B prompt_enforced (77.6%, 1.7%)", m14["prompt_enforced"]["utility"]["k"], 85, m14["prompt_enforced"]["violation_rate"]["k"], 120, "#1f6feb", "star", 10, 12, "start"),
        ("32B record (56.5%, 46.7%)", *s16["record"]["utility"], *s16["record"]["violation"], "#c0392b", "circle", -9, 14, "end"),
        ("32B prompt (55.3%, 18.3%)", *s16["prompt"]["utility"], *s16["prompt"]["violation"], "#c0392b", "square", 9, 14, "start"),
        ("32B prompt+norm (76.5%, 20.0%)", *s14c["utility"]["norm"], *s14c["violation_rate"]["norm"], "#c0392b", "diamond", 9, 4, "start"),
        ("32B enforced (65.9%, 5.0%)", *s16["enforced"]["utility"], *s16["enforced"]["violation"], "#c0392b", "triangle", 9, 11, "start"),
        ("32B prompt_enforced (64.7%, 5.0%)", *s16["prompt_enforced"]["utility"], *s16["prompt_enforced"]["violation"], "#c0392b", "triangle", 9, 23, "start"),
        ("32B DiD+norm (84.7%, 1.7%)", *s16b["utility"]["did_norm"], *s16b["violation_rate"]["did_norm"], "#c0392b", "star", 10, 12, "start"),
        ("32B DiD+norm+redact (87.1% / 82.4%*, 0.0%)", 74, 85, 0, 120, "#8e1b10", "star", 10, 14, "start"),
        ("Gemma4-31B record (71.8%, 42.5%)", 61, 85, 51, 120, "#0b8043", "circle", -9, -6, "end"),
        ("Gemma4-31B DiD (81.2% / 78.8%*, 0.0%)", 69, 85, 0, 120, "#0b8043", "triangle", 10, 14, "start"),
        ("Gemma4-31B prm & DiD+norm PEAK (89.4% / 84.7%*, 0.0%)", 76, 85, 0, 120, "#0b8043", "star", 10, -7, "start"),
        ("gpt-oss-20B record (45.9%, 36.7%)", 39, 85, 44, 120, "#00897b", "circle", 9, -4, "start"),
        ("gpt-oss-20B prompt (51.8%, 3.3%)", 44, 85, 4, 120, "#00897b", "square", 9, 12, "start"),
        ("gpt-oss-20B DiD+norm (58.8%, 0.8%)", 50, 85, 1, 120, "#00897b", "star", 10, -5, "start"),
    ]

    W, H = 980, 650
    ml, mr, mt, mb = 72, 240, 52, 62
    plot_w, plot_h = W - ml - mr, H - mt - mb
    xmax, ymax = 52.0, 104.0

    def sx(v):
        return ml + (v / xmax) * plot_w

    def sy(v):
        return mt + plot_h - (v / ymax) * plot_h

    out = [svg_header(W, H, "WardBench Pareto: Utility vs Violation Rate")]
    out.append(text(W / 2, 28, "Fig. 1 — Non-refuse clinical utility vs policy violation rate (dev, 95% Wilson CI on both axes)", size=13.5, anchor="middle", weight="bold"))
    out.append(rect(ml, mt, plot_w, plot_h, fill="#fafafa", stroke="#ccc"))
    out.append(line(ml, mt + plot_h, ml + plot_w, mt + plot_h, stroke="#222", width=1.5))
    out.append(line(ml, mt, ml, mt + plot_h, stroke="#222", width=1.5))
    out.append(text(ml + plot_w / 2, H - 18, "Policy violation rate (%, n=120 main tasks)  ← lower is better", size=11.5, anchor="middle", weight="bold"))
    out.append(
        f'<text x="20" y="{mt + plot_h / 2:.1f}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif" '
        f'font-size="11.5" font-weight="bold" fill="#111" transform="rotate(-90 20,{mt + plot_h / 2:.1f})">'
        f"Non-refuse clinical utility (%, n=85)  → higher is better</text>\n"
    )
    for tick in range(0, 51, 10):
        x = sx(tick)
        out.append(line(x, mt + plot_h, x, mt + plot_h + 5, stroke="#444", width=1))
        out.append(text(x, mt + plot_h + 18, f"{tick}%", size=10, anchor="middle", fill="#444"))
        out.append(line(x, mt, x, mt + plot_h, stroke="#e8e8e8", width=1, dash="3,3"))
    for tick in range(0, 101, 20):
        y = sy(tick)
        out.append(line(ml - 5, y, ml, y, stroke="#444", width=1))
        out.append(text(ml - 8, y + 4, f"{tick}%", size=10, anchor="end", fill="#444"))
        out.append(line(ml, y, ml + plot_w, y, stroke="#e8e8e8", width=1, dash="3,3"))

    # Trajectory polylines (14B and 32B)
    traj_14 = [
        (pct(m14["record"]["violation_rate"]["k"], 120), pct(m14["record"]["utility"]["k"], 85)),
        (pct(m14["prompt"]["violation_rate"]["k"], 120), pct(m14["prompt"]["utility"]["k"], 85)),
        (pct(m14["enforced"]["violation_rate"]["k"], 120), pct(m14["enforced"]["utility"]["k"], 85)),
        (pct(m14["prompt_enforced"]["violation_rate"]["k"], 120), pct(m14["prompt_enforced"]["utility"]["k"], 85)),
    ]
    traj_32 = [
        (pct(s16["record"]["violation"][0], 120), pct(s16["record"]["utility"][0], 85)),
        (pct(s16["prompt"]["violation"][0], 120), pct(s16["prompt"]["utility"][0], 85)),
        (pct(s14c["violation_rate"]["norm"][0], 120), pct(s14c["utility"]["norm"][0], 85)),
        (pct(s16b["violation_rate"]["did_norm"][0], 120), pct(s16b["utility"]["did_norm"][0], 85)),
        (0.0, pct(74, 85)),
    ]
    for traj, col in ((traj_14, "#1f6feb"), (traj_32, "#c0392b")):
        pts = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in traj)
        out.append(
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8" '
            f'stroke-opacity="0.55" stroke-dasharray="5,4"/>\n'
        )

    for label, uk, un, vk, vn, color, marker, dx, dy, anchor in points:
        u = pct(uk, un)
        v = pct(vk, vn)
        u_lo, u_hi = wilson_ci(uk, un)
        v_lo, v_hi = wilson_ci(vk, vn)
        x, y = sx(v), sy(u)
        y_lo, y_hi = sy(u_hi * 100), sy(u_lo * 100)
        x_lo, x_hi = sx(v_lo * 100), sx(v_hi * 100)
        # Vertical CI (utility)
        out.append(line(x, y_lo, x, y_hi, stroke=color, width=1.1))
        out.append(line(x - 3, y_lo, x + 3, y_lo, stroke=color, width=1.0))
        out.append(line(x - 3, y_hi, x + 3, y_hi, stroke=color, width=1.0))
        # Horizontal CI (violation rate)
        if vn > 0 and vk > 0:
            out.append(line(x_lo, y, x_hi, y, stroke=color, width=1.0, dash="2,2"))
        if marker == "circle":
            out.append(circle(x, y, 5.2, fill=color, stroke="#111", sw=0.8))
        elif marker == "square":
            out.append(rect(x - 4.8, y - 4.8, 9.6, 9.6, fill=color, stroke="#111", sw=0.8))
        elif marker == "diamond":
            out.append(
                f'<polygon points="{x:.1f},{y-6.5:.1f} {x+6.5:.1f},{y:.1f} {x:.1f},{y+6.5:.1f} {x-6.5:.1f},{y:.1f}" '
                f'fill="{color}" stroke="#111" stroke-width="0.8"/>\n'
            )
        elif marker == "triangle":
            out.append(
                f'<polygon points="{x:.1f},{y-6.5:.1f} {x+6.5:.1f},{y+5.5:.1f} {x-6.5:.1f},{y+5.5:.1f}" '
                f'fill="{color}" stroke="#111" stroke-width="0.8"/>\n'
            )
        else:  # star/bullseye
            out.append(circle(x, y, 7.0, fill=color, stroke="#111", sw=1.1))
            out.append(circle(x, y, 2.6, fill="#fff", stroke="#111", sw=0.6))
        w_font = "bold" if "PEAK" in label or "ToolSolver" in label else "normal"
        out.append(text(x + dx, y + dy, label, size=8.3, anchor=anchor, weight=w_font, fill=color if w_font == "bold" else "#222"))

    # Legend box
    lx, ly = W - mr + 14, mt + 10
    out.append(rect(lx - 6, ly - 14, mr - 22, 345, fill="#ffffff", stroke="#ddd", rx=4))
    out.append(text(lx, ly + 2, "Model Families", size=11, weight="bold"))
    legend = [
        ("#0a7a2f", "ToolSolver (reference)"),
        ("#0b8043", "Gemma 4 31B-IT (Q4_K_M)"),
        ("#c0392b", "Qwen3-32B (Q4_K_M)"),
        ("#1f6feb", "Qwen3-14B (Q4_K_M)"),
        ("#00897b", "OpenAI gpt-oss-20B (MXFP4)"),
        ("#6b4ce6", "Qwen2.5-7B-FC"),
        ("#8a6500", "MedGemma-4B-IT (react_json)"),
        ("#666666", "OpenBioLLM-8B (react_json)"),
    ]
    for i, (col, lab) in enumerate(legend):
        yy = ly + 20 + i * 17
        out.append(circle(lx + 7, yy - 4, 4.5, fill=col, stroke="#111", sw=0.6))
        out.append(text(lx + 18, yy, lab, size=9.1))

    my = ly + 170
    out.append(text(lx, my, "Policy Visibility / Mode", size=11, weight="bold"))
    shapes = [
        ("circle", "record (no policy in prompt)"),
        ("square", "prompt (policy in prompt)"),
        ("diamond", "prompt + --api-norm (S14)"),
        ("triangle", "enforced / prompt_enforced"),
        ("star", "Defense-in-Depth peak / ceiling"),
    ]
    for i, (sh, lab) in enumerate(shapes):
        yy = my + 18 + i * 17
        cx_i, cy_i = lx + 7, yy - 4
        if sh == "circle":
            out.append(circle(cx_i, cy_i, 4.5, fill="#555", stroke="#111", sw=0.6))
        elif sh == "square":
            out.append(rect(cx_i - 4.2, cy_i - 4.2, 8.4, 8.4, fill="#555", stroke="#111", sw=0.6))
        elif sh == "diamond":
            out.append(f'<polygon points="{cx_i:.1f},{cy_i-5.5:.1f} {cx_i+5.5:.1f},{cy_i:.1f} {cx_i:.1f},{cy_i+5.5:.1f} {cx_i-5.5:.1f},{cy_i:.1f}" fill="#555" stroke="#111" stroke-width="0.6"/>\n')
        elif sh == "triangle":
            out.append(f'<polygon points="{cx_i:.1f},{cy_i-5.5:.1f} {cx_i+5.5:.1f},{cy_i+4.5:.1f} {cx_i-5.5:.1f},{cy_i+4.5:.1f}" fill="#555" stroke="#111" stroke-width="0.6"/>\n')
        else:
            out.append(circle(cx_i, cy_i, 5.5, fill="#0b8043", stroke="#111", sw=0.9))
            out.append(circle(cx_i, cy_i, 2.0, fill="#fff", stroke="#111", sw=0.5))
        out.append(text(lx + 18, yy, lab, size=9.0))

    out.append(text(lx, my + 114, "Gemma4-31B DiD+norm: 89.4% (84.7%*)", size=8.8, weight="bold", fill="#0b8043"))
    out.append(text(lx, my + 127, "Qwen3-32B DiD+norm+red: 87.1% (82.4%*)", size=8.8, weight="bold", fill="#8e1b10"))
    out.append(text(lx, my + 140, "Both at 0/120 (0.0%) violations", size=8.8, weight="bold", fill="#222"))
    out.append(svg_footer())
    return "".join(out)


# ---------------------------------------------------------------------------
# Figure 2 — Static vs dynamic Consent
# ---------------------------------------------------------------------------

def fig2_static_dynamic() -> str:
    # Exact bucket counts (n=30 static_role_purpose, n=30 dynamic_consent):
    # - 14B record: static 23/30 (76.7%), dynamic 19/30 (63.3%), dyn consent_check 0/30 (0.0%)
    # - 14B prompt: static 1/30 (3.3%), dynamic 18/30 (60.0%), dyn consent_check 1/30 (3.3%)
    # - 32B prompt: static 4/30 (13.3%), dynamic 11/30 (36.7%), dyn consent_check 5/30 (16.7%)
    # - 14B prompt + --prefetch-consent: static 1/30 (3.3%), dynamic 5/30 (16.7%), dyn consent_check 0/30 (0.0%, in-context)
    # - 14B prompt + --strict-redaction-prompt v1/v2:
    #     v1 (S15): dynamic viol 6/30 (20.0%), dyn consent_check 29/30 (96.7%);
    #     v2 (S15b): clears the 6 remaining PSY e.g.-leaks -> 0/30 (0.0%) dynamic violations!
    # - 14B prompt_enforced (S8): static 0/30 (0.0%), dynamic 1/30 (3.3%), dyn consent_check 2/30 (6.7%)
    # - 32B prompt_enforced + --api-norm (S16b): static 0/30 (0.0%), dynamic 1/30 (3.3%), dyn consent_check 17/30 (56.7%; 31/120=25.8% overall)
    rows = [
        ("14B record", 76.7, 63.3, 0.0, "23/30", "19/30", "0/30"),
        ("14B prompt", 3.3, 60.0, 3.3, "1/30", "18/30", "1/30"),
        ("32B prompt", 13.3, 36.7, 16.7, "4/30", "11/30", "5/30"),
        ("14B prompt + prefetch", 3.3, 16.7, 0.0, "1/30", "5/30", "0/30*"),
        ("14B prompt + redact v1", 3.3, 20.0, 96.7, "1/30", "6/30", "29/30"),
        ("14B prompt + redact v2", 3.3, 0.0, 96.7, "1/30", "0/30", "29/30"),
        ("14B prompt_enforced", 0.0, 3.3, 6.7, "0/30", "1/30", "2/30"),
        ("32B DiD + api-norm", 0.0, 3.3, 56.7, "0/30", "1/30", "17/30"),
        ("32B DiD+norm+redact", 0.0, 0.0, 63.3, "0/30", "0/30", "19/30"),
    ]

    W, H = 980, 540
    ml, mr, mt, mb = 68, 36, 56, 92
    plot_w, plot_h = W - ml - mr, H - mt - mb
    n = len(rows)
    group_w = plot_w / n
    bar_w = group_w / 4.3
    ymax = 105.0

    def sy(v):
        return mt + plot_h - (v / ymax) * plot_h

    out = [svg_header(W, H, "Static Role/Purpose vs Dynamic FHIR Consent")]
    out.append(
        text(
            W / 2,
            28,
            "Fig. 2 — Static Role/Purpose (n=30) vs Dynamic FHIR Consent (n=30): Violations & Epistemic Checks",
            size=13.5,
            anchor="middle",
            weight="bold",
        )
    )
    out.append(rect(ml, mt, plot_w, plot_h, fill="#fafafa", stroke="#ccc"))
    out.append(line(ml, mt + plot_h, ml + plot_w, mt + plot_h, stroke="#222", width=1.5))
    out.append(line(ml, mt, ml, mt + plot_h, stroke="#222", width=1.5))
    for tick in range(0, 101, 20):
        y = sy(tick)
        out.append(line(ml - 4, y, ml, y, stroke="#444", width=1))
        out.append(text(ml - 8, y + 4, f"{tick}%", size=10, anchor="end", fill="#444"))
        out.append(line(ml, y, ml + plot_w, y, stroke="#e8e8e8", width=1, dash="3,3"))
    out.append(
        f'<text x="20" y="{mt + plot_h / 2:.1f}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif" '
        f'font-size="11.5" font-weight="bold" fill="#111" transform="rotate(-90 20,{mt + plot_h / 2:.1f})">'
        f"Bucket rate (%, n=30 per bucket)</text>\n"
    )

    colors = {"static": "#3b6998", "dynamic": "#c0392b", "consent": "#1e824c"}
    for i, (lab, st, dy, ck, st_s, dy_s, ck_s) in enumerate(rows):
        gx = ml + i * group_w + group_w * 0.11
        for j, (val, key, frac) in enumerate(((st, "static", st_s), (dy, "dynamic", dy_s), (ck, "consent", ck_s))):
            x = gx + j * (bar_w + 3)
            y = sy(val)
            h = max(1.5, mt + plot_h - y)
            out.append(rect(x, mt + plot_h - h, bar_w, h, fill=colors[key], stroke="#222", sw=0.5))
            out.append(text(x + bar_w / 2, mt + plot_h - h - 11, f"{val:.1f}%", size=7.6, anchor="middle", weight="bold", fill="#222"))
            out.append(text(x + bar_w / 2, mt + plot_h - h - 2, f"({frac})", size=6.8, anchor="middle", fill="#555"))
        # X-axis group label
        cx = ml + i * group_w + group_w / 2
        parts = lab.split(" + ")
        if len(parts) == 1:
            out.append(text(cx, mt + plot_h + 18, lab, size=9.2, anchor="middle", weight="bold"))
        else:
            out.append(text(cx, mt + plot_h + 16, parts[0], size=9.0, anchor="middle", weight="bold"))
            out.append(text(cx, mt + plot_h + 29, "+ " + parts[1], size=8.6, anchor="middle", fill="#333"))

    # Legend & notes
    ly = H - 34
    out.append(rect(ml, ly - 10, 12, 12, fill=colors["static"], stroke="#222", sw=0.5))
    out.append(text(ml + 17, ly, "Static Role/Purpose Viol. (n=30)", size=10, weight="bold"))
    out.append(rect(ml + 235, ly - 10, 12, 12, fill=colors["dynamic"], stroke="#222", sw=0.5))
    out.append(text(ml + 252, ly, "Dynamic FHIR Consent Viol. (n=30)", size=10, weight="bold"))
    out.append(rect(ml + 490, ly - 10, 12, 12, fill=colors["consent"], stroke="#222", sw=0.5))
    out.append(text(ml + 507, ly, "Dynamic Consent-Check Rate (n=30)", size=10, weight="bold"))
    out.append(
        text(
            ml,
            H - 12,
            "*Note: prefetch supplies Consent in context (18/30→5/30 dyn viol, McNemar p=2.4e-4). Strict-redact v1 lifts checks 1/30→29/30 (p=7.5e-9); v2 clears all 6 PSY e.g.-leaks (6/30→0/30). 32B DiD+norm overall viol=2/120 (1.7%), overall Consent checks=31/120 (25.8%).",
            size=8.3,
            fill="#444",
        )
    )
    out.append(svg_footer())
    return "".join(out)


# ---------------------------------------------------------------------------
# Figure 3 — Four construct-validity traps
# ---------------------------------------------------------------------------

def base_panel(y, h):
    return y + h - 48


def ay_panel(y, h, v, ymax=105.0):
    top = y + 60
    base = base_panel(y, h)
    return base - (v / ymax) * (base - top)


def fig3_traps() -> str:
    W, H = 1000, 720
    out = [svg_header(W, H, "Five Construct Validity Traps")]
    out.append(
        text(
            W / 2,
            28,
            "Fig. 3 — Five Construct-Validity Traps Uncovered in WardBench v0.4 (Panels A–D + Trap 5 Grounding)",
            size=13.5,
            anchor="middle",
            weight="bold",
        )
    )

    panels = [
        (28, 48, 462, 304, "A. Trap 1: Environment Search Truncation (S1, S2c)"),
        (510, 48, 462, 304, "B. Trap 2: Permitted-Twin Framing & 32B Paradox (S9, S12b)"),
        (28, 380, 462, 304, "C. Trap 3: False-Refusal Conflation & Ironic Leak (S7, S8b)"),
        (510, 380, 462, 304, "D. Trap 4: FHIR Schema Aliasing Scale-Inversion (S14, S14c)"),
    ]

    def panel_box(x, y, w, h, title):
        parts = [rect(x, y, w, h, fill="#fbfbfb", stroke="#bbb", rx=4)]
        parts.append(text(x + 12, y + 22, title, size=11.5, weight="bold"))
        return parts

    # Panel A — before/after bars
    x, y, w, h, title = panels[0]
    out.extend(panel_box(x, y, w, h, title))
    out.append(text(x + 12, y + 40, "Synthea UUIDs pushed pt-* rows past 3500-char window; SNOMED tag = 5–7%", size=9.2, fill="#444"))
    series_a = [
        ("ToolSolver", 62.4, 100.0, "53/85", "85/85"),
        ("14B record", 48.2, 65.9, "41/85", "56/85"),
        ("14B prompt", 49.4, 62.4, "42/85", "53/85"),
    ]
    bx0 = x + 48
    bw = 38
    gap = 132
    base = base_panel(y, h)
    out.append(line(x + 30, base, x + w - 20, base, stroke="#444", width=1))
    for i, (lab, before, after, b_fr, a_fr) in enumerate(series_a):
        xx = bx0 + i * gap
        yb, ya = ay_panel(y, h, before), ay_panel(y, h, after)
        out.append(rect(xx, yb, bw, base - yb, fill="#95a5a6", stroke="#333", sw=0.6))
        out.append(rect(xx + bw + 6, ya, bw, base - ya, fill="#0a7a2f", stroke="#333", sw=0.6))
        out.append(text(xx + bw + 3, base + 15, lab, size=9.5, anchor="middle", weight="bold"))
        out.append(text(xx + bw / 2, yb - 11, f"{before:.1f}%", size=8.2, anchor="middle", weight="bold"))
        out.append(text(xx + bw / 2, yb - 2, f"({b_fr})", size=7.2, anchor="middle", fill="#555"))
        out.append(text(xx + bw + 6 + bw / 2, ya - 11, f"{after:.1f}%", size=8.2, anchor="middle", weight="bold", fill="#0a7a2f"))
        out.append(text(xx + bw + 6 + bw / 2, ya - 2, f"({a_fr})", size=7.2, anchor="middle", fill="#0a7a2f"))
    out.append(rect(x + 20, y + h - 20, 10, 10, fill="#95a5a6", stroke="#333", sw=0.5))
    out.append(text(x + 35, y + h - 11, "Pre-fix utility (v0.3)", size=9))
    out.append(rect(x + 175, y + h - 20, 10, 10, fill="#0a7a2f", stroke="#333", sw=0.5))
    out.append(text(x + 190, y + h - 11, "Post fhir_search ranking fix (v0.4)", size=9))

    # Panel B — capability bars
    x, y, w, h, title = panels[1]
    out.extend(panel_box(x, y, w, h, title))
    out.append(text(x + 12, y + 40, "S9: record 60%→90% (p=0.0039); S12b: 32B Consent-aware 46.7%→53.3%", size=9.2, fill="#444"))
    series_b = [
        ("14B record", 60.0, 90.0, "18/30", "27/30"),
        ("14B prompt", 66.7, 80.0, "20/30", "24/30"),
        ("32B prompt", 46.7, 53.3, "14/30", "16/30*"),
    ]
    bx0 = x + 48
    base = base_panel(y, h)
    out.append(line(x + 30, base, x + w - 20, base, stroke="#444", width=1))
    for i, (lab, a, b, af, bf) in enumerate(series_b):
        xx = bx0 + i * 132
        ya, yb = ay_panel(y, h, a), ay_panel(y, h, b)
        out.append(rect(xx, ya, 38, base - ya, fill="#3b6998", stroke="#333", sw=0.6))
        out.append(rect(xx + 44, yb, 38, base - yb, fill="#e67e22", stroke="#333", sw=0.6))
        out.append(text(xx + 41, base + 15, lab, size=9.5, anchor="middle", weight="bold"))
        out.append(text(xx + 19, ya - 11, f"{a:.1f}%", size=8.2, anchor="middle", weight="bold"))
        out.append(text(xx + 19, ya - 2, f"({af})", size=7.2, anchor="middle", fill="#555"))
        out.append(text(xx + 63, yb - 11, f"{b:.1f}%", size=8.2, anchor="middle", weight="bold", fill="#b85d00"))
        out.append(text(xx + 63, yb - 2, f"({bf})", size=7.2, anchor="middle", fill="#b85d00"))
    out.append(rect(x + 20, y + h - 20, 10, 10, fill="#3b6998", stroke="#333", sw=0.5))
    out.append(text(x + 35, y + h - 11, "Same-text -perm (headline)", size=9))
    out.append(rect(x + 205, y + h - 20, 10, 10, fill="#e67e22", stroke="#333", sw=0.5))
    out.append(text(x + 220, y + h - 11, "Clinical rephrase / *Consent-aware", size=9))

    # Panel C — refusal split & ironic leak
    x, y, w, h, title = panels[2]
    out.extend(panel_box(x, y, w, h, title))
    out.append(text(x + 12, y + 40, "7B false_refusal is 100% retrieval miss (0 policy refusals); 14B leaks inside refusals", size=9.0, fill="#444"))
    series_c = [
        ("7B rec", 66.3, 0.0, 0.0, "55/83", "0/83"),
        ("7B prm", 69.0, 0.0, 0.0, "58/84", "0/84"),
        ("14B prm", 13.3, 7.2, 5.8, "11/83", "6/83"),
        ("32B prm", 22.9, 4.8, 3.3, "19/83", "4/83"),
    ]
    base = base_panel(y, h)
    out.append(line(x + 30, base, x + w - 20, base, stroke="#444", width=1))
    for i, (lab, ret_p, por_p, rwd_p, ret_f, por_f) in enumerate(series_c):
        xx = x + 42 + i * 102
        y_ret = ay_panel(y, h, ret_p)
        y_por = ay_panel(y, h, por_p)
        y_rwd = ay_panel(y, h, rwd_p)
        out.append(rect(xx, y_ret, 24, max(1.5, base - y_ret), fill="#7f8c8d", stroke="#333", sw=0.5))
        out.append(rect(xx + 26, y_por, 24, max(1.5, base - y_por), fill="#2980b9", stroke="#333", sw=0.5))
        out.append(rect(xx + 52, y_rwd, 24, max(1.5, base - y_rwd), fill="#c0392b", stroke="#333", sw=0.5))
        out.append(text(xx + 12, y_ret - 4, f"{ret_p:.0f}%", size=7.5, anchor="middle", weight="bold"))
        out.append(text(xx + 38, y_por - 4, f"{por_p:.0f}%", size=7.5, anchor="middle", fill="#2980b9", weight="bold"))
        out.append(text(xx + 64, y_rwd - 4, f"{rwd_p:.1f}%", size=7.5, anchor="middle", fill="#c0392b", weight="bold"))
        out.append(text(xx + 38, base + 15, lab, size=9.2, anchor="middle", weight="bold"))
    out.append(rect(x + 16, y + h - 20, 10, 10, fill="#7f8c8d", stroke="#333", sw=0.5))
    out.append(text(x + 30, y + h - 11, "Retrieval miss", size=8.5))
    out.append(rect(x + 125, y + h - 20, 10, 10, fill="#2980b9", stroke="#333", sw=0.5))
    out.append(text(x + 139, y + h - 11, "True policy over-refusal", size=8.5))
    out.append(rect(x + 285, y + h - 20, 10, 10, fill="#c0392b", stroke="#333", sw=0.5))
    out.append(text(x + 299, y + h - 11, "Refusal w/ disclosure (/120)", size=8.5))

    # Panel D — scale util before/after api-norm
    x, y, w, h, title = panels[3]
    out.extend(panel_box(x, y, w, h, title))
    out.append(text(x + 12, y + 40, "32B McNemar b=1,c=19, p=4.0e-5 (+21.2 pp); bad_rtype 19/120 → 0/120", size=9.2, fill="#444"))
    series_d = [
        ("7B-FC prompt", 20.0, 29.4, "17/85", "25/85"),
        ("14B prompt", 62.4, 65.9, "53/85", "56/85"),
        ("32B prompt", 55.3, 76.5, "47/85", "65/85"),
    ]
    bx0 = x + 48
    base = base_panel(y, h)
    out.append(line(x + 30, base, x + w - 20, base, stroke="#444", width=1))
    for i, (lab, before, after, bf, af) in enumerate(series_d):
        xx = bx0 + i * 132
        yb, ya = ay_panel(y, h, before), ay_panel(y, h, after)
        out.append(rect(xx, yb, 38, base - yb, fill="#95a5a6", stroke="#333", sw=0.6))
        out.append(rect(xx + 44, ya, 38, base - ya, fill="#c0392b", stroke="#333", sw=0.6))
        out.append(text(xx + 41, base + 15, lab, size=9.2, anchor="middle", weight="bold"))
        out.append(text(xx + 19, yb - 11, f"{before:.1f}%", size=8.2, anchor="middle", weight="bold"))
        out.append(text(xx + 19, yb - 2, f"({bf})", size=7.2, anchor="middle", fill="#555"))
        out.append(text(xx + 63, ya - 11, f"{after:.1f}%", size=8.2, anchor="middle", weight="bold", fill="#c0392b"))
        out.append(text(xx + 63, ya - 2, f"({af})", size=7.2, anchor="middle", fill="#c0392b"))
    # Monotonic trend line across the 3 normalized bars
    p1 = (bx0 + 63, ay_panel(y, h, 29.4))
    p2 = (bx0 + 132 + 63, ay_panel(y, h, 65.9))
    p3 = (bx0 + 264 + 63, ay_panel(y, h, 76.5))
    out.append(
        f'<polyline points="{p1[0]:.1f},{p1[1]:.1f} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}" '
        f'fill="none" stroke="#0a7a2f" stroke-width="2.0" stroke-dasharray="4,3"/>\n'
    )
    out.append(rect(x + 20, y + h - 20, 10, 10, fill="#95a5a6", stroke="#333", sw=0.5))
    out.append(text(x + 35, y + h - 11, "Raw prompt (non-monotonic)", size=9))
    out.append(rect(x + 210, y + h - 20, 10, 10, fill="#c0392b", stroke="#333", sw=0.5))
    out.append(text(x + 225, y + h - 11, "With --api-norm (monotonic: 29%→66%→76%)", size=9))

    out.append(svg_footer())
    return "".join(out)


def validate_against_results(summary: dict) -> None:
    """Cross-check summary cells against saved result JSON task arrays."""
    results = REPO / "results" / "v0.4"
    samples = [
        ("qwen3-14b_dev_prompt.json", 180),
        ("qwen3-32b_dev_prompt_enforced_norm.json", 180),
        ("qwen3-32b_dev_prompt_norm.json", 180),
    ]
    for fname, expect_rows in samples:
        path = results / fname
        if not path.exists():
            raise SystemExit(f"missing required result file: {path}")
        doc = json.loads(path.read_text())
        agent_blocks = [v for k, v in doc.items() if k != "meta" and isinstance(v, dict) and "tasks" in v]
        if not agent_blocks:
            raise SystemExit(f"no agent block with 'tasks' in {fname}")
        n = len(agent_blocks[0]["tasks"])
        if n != expect_rows:
            raise SystemExit(f"row-count mismatch in {fname}: got {n}, expected {expect_rows}")
    peak = summary["s16b_did_plus_api_norm"]["utility"]["did_norm"]
    if peak != [72, 85]:
        raise SystemExit(f"unexpected peak utility in summary: {peak}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = json.loads(SUMMARY.read_text())
    validate_against_results(summary)
    figs = {
        "fig1_pareto_frontier.svg": fig1_pareto(summary),
        "fig2_static_vs_dynamic_consent.svg": fig2_static_dynamic(),
        "fig3_construct_validity_traps.svg": fig3_traps(),
    }
    inkscape = shutil.which("inkscape")
    for name, body in figs.items():
        path = OUT_DIR / name
        path.write_text(body)
        print(f"wrote {path} ({len(body)} bytes)")
        if inkscape:
            pdf_path = path.with_suffix(".pdf")
            subprocess.run([inkscape, str(path), f"--export-filename={pdf_path}"], check=True)
            print(f"wrote {pdf_path} ({pdf_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
