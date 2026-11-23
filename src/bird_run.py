import csv
import json
import sqlite3
import sys

import anthropic

from run import MODEL, EFFORT, execute, extract_sql, show  # run.py also loads .env

sys.path.insert(0, "third_party/bird_eval")
from evaluation import execute_sql as bird_official_match  # official BIRD scorer, vendored unmodified

BIRD_DB = "data/raw/bird_db/dev_databases/{db}/{db}.sqlite"
ARMS = ["with_evidence", "without_evidence"]

# The two arms differ only in the evidence block; everything else is byte-identical.
PROMPT = """Here is the schema of a SQLite database:

{schema}
{evidence_block}
Write a single SQLite query that answers this question:
{question}

Reply with only the SQL query. No explanation, no markdown."""
EVIDENCE_BLOCK = "\nDomain knowledge that may help:\n{evidence}\n"


def get_schema(db_id):
    con = sqlite3.connect(f"file:{BIRD_DB.format(db=db_id)}?mode=ro", uri=True)
    rows = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL").fetchall()
    con.close()
    return "\n\n".join(r[0].strip() + ";" for r in rows)


def build_prompt(ex, arm):
    block = EVIDENCE_BLOCK.format(evidence=ex["evidence"]) if arm == "with_evidence" else ""
    return PROMPT.format(schema=get_schema(ex["db_id"]), evidence_block=block, question=ex["question"])


def generate(client, prompt):
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, response.stop_reason, response.usage.input_tokens, response.usage.output_tokens


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    sample = json.load(open(f"data/bird_sample_n{n}.json"))
    client = anthropic.Anthropic(max_retries=0)  # no retries in this phase
    out = []
    f = open(f"results/phase1_bird_n{n}.csv", "w", newline="")  # rows are written as they finish
    w = None
    for i, ex in enumerate(sample):
        db_path = BIRD_DB.format(db=ex["db_id"])
        gold_rows, gold_error = execute(db_path, ex["gold_sql"])
        for arm in ARMS:
            row = {"question_id": ex["question_id"], "db_id": ex["db_id"], "difficulty": ex["difficulty"], "arm": arm,
                   "question": ex["question"], "evidence": ex["evidence"], "gold_sql": ex["gold_sql"],
                   "model": MODEL, "effort": EFFORT, "raw_output": None, "gen_sql": None, "stop_reason": None,
                   "input_tokens": None, "output_tokens": None, "api_error": None, "gold_error": gold_error}
            try:
                row["raw_output"], row["stop_reason"], row["input_tokens"], row["output_tokens"] = generate(client, build_prompt(ex, arm))
                row["gen_sql"] = extract_sql(row["raw_output"])
            except Exception as e:
                row["api_error"] = f"{type(e).__name__}: {e}"

            gen_rows, row["gen_error"] = execute(db_path, row["gen_sql"]) if row["gen_sql"] else (None, "no SQL generated")
            row["gold_result"], row["gen_result"] = show(gold_rows), show(gen_rows)
            # exec_status is for analysis only; the accuracy number comes from the official scorer.
            # Only SQL that already ran read-only within the timeout is passed to the official scorer.
            if row["gen_error"]:
                row["exec_status"], row["ex"] = "error", 0
            else:
                row["exec_status"] = "empty" if len(gen_rows) == 0 else "ok"
                row["ex"] = bird_official_match(row["gen_sql"], ex["gold_sql"], db_path)
            print(f"[{i + 1}/{len(sample)}] q{ex['question_id']} {arm:16s} status={row['exec_status']} EX={row['ex']}", flush=True)
            out.append(row)
            if w is None:
                w = csv.DictWriter(f, fieldnames=list(row.keys()))
                w.writeheader()
            w.writerow(row)
            f.flush()
    f.close()

    for arm in ARMS:
        rows = [r for r in out if r["arm"] == arm]
        n, correct = len(rows), sum(r["ex"] for r in rows)
        errored = sum(r["exec_status"] == "error" for r in rows)
        print(f"{arm:16s}: correct {correct}/{n} | errored {errored}/{n} | ran but wrong (silent) {n - correct - errored}/{n}")

    pairs = {}
    for r in out:
        pairs.setdefault(r["question_id"], {})[r["arm"]] = r["ex"]
    cells = [(p["with_evidence"], p["without_evidence"]) for p in pairs.values()]
    print(f"paired: both right {cells.count((1, 1))} | only with evidence {cells.count((1, 0))} | "
          f"only without evidence {cells.count((0, 1))} | both wrong {cells.count((0, 0))}")
    print(f"tokens: input {sum(r['input_tokens'] or 0 for r in out)}, output {sum(r['output_tokens'] or 0 for r in out)}")


if __name__ == "__main__":
    main()
