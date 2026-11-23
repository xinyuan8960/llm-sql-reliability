import json
import random

SEED = 0
N = 10

dev = json.load(open("data/raw/spider_data/dev.json"))
indices = sorted(random.Random(SEED).sample(range(len(dev)), N))
sample = [
    {"dev_index": i, "db_id": dev[i]["db_id"], "question": dev[i]["question"], "gold_sql": dev[i]["query"]}
    for i in indices
]
json.dump(sample, open("data/sample.json", "w"), indent=2, ensure_ascii=False)
print(f"saved {len(sample)} examples (seed={SEED}) to data/sample.json")
for ex in sample:
    print(f"  [{ex['dev_index']}] {ex['db_id']}: {ex['question']}")
