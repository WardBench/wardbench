# R1 Dataset

Author: Vadim Nareyko.

Synthea Build-Version `d9d07a6`, seeds `20261019` / extra `20261020`.
Eligible patients 149; pools 30/30. Dev tasks: 120.

| category | n |
|---|---:|
| adversarial | 30 |
| allowed | 30 |
| boundary | 30 |
| denied | 30 |

| family | n |
|---|---:|
| adv_disclose_psy | 3 |
| adv_exfil_deid | 3 |
| adv_exfil_latest_note | 2 |
| adv_exfil_meds | 3 |
| adv_exfil_older_note | 3 |
| adv_exfil_registration | 2 |
| adv_override_inactive | 1 |
| adv_read_all_patients | 3 |
| adv_read_others_dx | 2 |
| adv_spoof_billing | 2 |
| adv_spoof_override | 2 |
| adv_spoof_related | 2 |
| adv_unauthorized_write | 1 |
| adv_write_hba1c | 1 |
| allowed_list_conditions | 3 |
| allowed_list_conditions_nurse | 3 |
| allowed_list_meds | 3 |
| allowed_meds_physician | 3 |
| allowed_note_key_fact | 3 |
| allowed_order_assist | 3 |
| allowed_order_hba1c | 3 |
| allowed_read_hba1c | 3 |
| allowed_read_hba1c_permit | 3 |
| allowed_summarize_note | 3 |
| boundary_billing_confirm | 3 |
| boundary_billing_date | 3 |
| boundary_deid_age | 3 |
| boundary_deid_dx_hba1c | 3 |
| boundary_deid_research | 3 |
| boundary_psy_meds_ok | 3 |
| boundary_psy_omit | 3 |
| boundary_psy_short | 3 |
| boundary_registration_demo | 3 |
| boundary_registration_name | 3 |
| denied_billing_notes | 3 |
| denied_billing_value | 3 |
| denied_registration_dx | 3 |
| denied_registration_labs | 3 |
| denied_related_email | 3 |
| denied_related_results | 3 |
| denied_research_inactive | 3 |
| denied_research_meds | 3 |
| denied_research_no_consent | 3 |
| denied_research_opt_out | 3 |

Schema additions: `template`, `family`, `variant`, `base_task_id`; `inject_text_start`.
Patient reuse: each patient ≤6 tasks; each (template, patient, variant) unique.
Instruction variants 1–3 used in dev; 4–5 reserved for test.
