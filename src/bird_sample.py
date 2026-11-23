import json
import random
import sys

from run import execute  # same read-only executor (10 s timeout) as Phase 0

SEED = 0
N = int(sys.argv[1]) if len(sys.argv) > 1 else 10
OUT = f"data/bird_sample_n{N}.json"
BIRD_JSON = "data/raw/bird_hf/dev_20251106.json"
BIRD_DB = "data/raw/bird_db/dev_databases/{db}/{db}.sqlite"

dev = json.load(open(BIRD_JSON))
with_evidence = [d for d in dev if d["evidence"].strip()]

# Keep questions whose gold answer is a single value (1 row x 1 column) on the released DB.
eligible, gold_failed = [], 0
for d in with_evidence:
    rows, err = execute(BIRD_DB.format(db=d["db_id"]), d["SQL"])
    if err:
        gold_failed += 1
    elif len(rows) == 1 and len(rows[0]) == 1:
        eligible.append(d)

print(f"dev: {len(dev)} | non-empty evidence: {len(with_evidence)} | gold failed/timed out: {gold_failed} | single-value gold: {len(eligible)}")

picked = sorted(random.Random(SEED).sample(eligible, N), key=lambda d: d["question_id"])
sample = [
    {"question_id": d["question_id"], "db_id": d["db_id"], "difficulty": d["difficulty"],
     "question": d["question"], "evidence": d["evidence"], "gold_sql": d["SQL"]}
    for d in picked
]
json.dump(sample, open(OUT, "w"), indent=2, ensure_ascii=False)
print(f"saved {len(sample)} examples (seed={SEED}) to {OUT}")
for ex in sample:
    print(f"  [{ex['question_id']}] {ex['db_id']} ({ex['difficulty']}): {ex['question']}")
