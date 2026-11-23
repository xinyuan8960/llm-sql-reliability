import csv
import random
import sys

SEED = 0
n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
results = list(csv.DictReader(open(f"results/phase1_bird_n{n}.csv")))

# Questions where the arms disagree, or both are wrong (i.e. not both right).
# Both arms' rows are included for these questions, so inclusion itself does not reveal the verdict.
by_q = {}
for r in results:
    by_q.setdefault(r["question_id"], []).append(r)
selected_q = [q for q, rows in by_q.items() if not all(r["ex"] == "1" for r in rows)]
rows = [r for q in selected_q for r in by_q[q]]

rng = random.Random(SEED)
rng.shuffle(rows)
ids = rng.sample(range(16**6), len(rows))  # opaque, unique, unrelated to question_id or arm

blind_cols = ["item_id", "question", "evidence", "gold_sql", "generated_sql", "gold_result", "generated_result", "label"]
key_cols = ["item_id", "question_id", "db_id", "difficulty", "arm", "ex", "exec_status"]
with open(f"results/adjudication_blind_n{n}.csv", "w", newline="") as fb, open(f"results/adjudication_key_n{n}.csv", "w", newline="") as fk:
    wb, wk = csv.DictWriter(fb, fieldnames=blind_cols), csv.DictWriter(fk, fieldnames=key_cols)
    wb.writeheader()
    wk.writeheader()
    for item_id, r in zip(ids, rows):
        item_id = f"{item_id:06x}"
        wb.writerow({"item_id": item_id, "question": r["question"], "evidence": r["evidence"], "gold_sql": r["gold_sql"],
                     "generated_sql": r["gen_sql"] or r["api_error"] or "", "gold_result": r["gold_result"],
                     "generated_result": r["gen_result"] or r["gen_error"] or "", "label": ""})
        wk.writerow({"item_id": item_id, **{c: r[c] for c in key_cols[1:]}})

print(f"{len(by_q)} questions | selected {len(selected_q)} (not both right) | {len(rows)} rows to label")
print(f"blind file: results/adjudication_blind_n{n}.csv | key (do not open before labelling): results/adjudication_key_n{n}.csv")
