import csv
import json
import re
import sqlite3
import sys
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()  # reads ANTHROPIC_API_KEY from .env at the repo root (gitignored)
sys.path.insert(0, "third_party/test_suite_sql_eval")
from exec_eval import eval_exec_match  # official Spider scorer, vendored unmodified

MODEL = "claude-sonnet-5-5"
EFFORT = "high"  # API default for this model, pinned explicitly for reproducibility
TIMEOUT_S = 10
SPIDER_DB = "data/raw/spider_data/database/{db}/{db}.sqlite"  # original DB -> EX
SUITE_DB = "data/raw/testsuite/database/{db}/{db}.sqlite"  # dir with all variants -> TS

PROMPT = """Here is the schema of a SQLite database:

{schema}

Write a single SQLite query that answers this question:
{question}

Reply with only the SQL query. No explanation, no markdown."""


def get_schema(db_id):
    con = sqlite3.connect(f"file:{SPIDER_DB.format(db=db_id)}?mode=ro", uri=True)
    rows = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL").fetchall()
    con.close()
    return "\n\n".join(r[0].strip() + ";" for r in rows)


def generate(client, schema, question):
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": PROMPT.format(schema=schema, question=question)}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, response.stop_reason, response.usage.input_tokens, response.usage.output_tokens


def extract_sql(text):
    # Only strips a markdown fence if the model added one anyway; raw text is kept in the CSV.
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip()


def execute(db_path, sql):
    # Read-only, with a real timeout (the official scorer's timeout cannot interrupt sqlite).
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.text_factory = lambda b: b.decode(errors="ignore")  # same decoding as the official scorer
    deadline = time.time() + TIMEOUT_S
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10000)
    try:
        return con.execute(sql).fetchall(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    finally:
        con.close()


def official_match(db_path, gen_sql, gold_sql):
    return eval_exec_match(db=db_path, p_str=gen_sql, g_str=gold_sql,
                           plug_value=False, keep_distinct=False, progress_bar_for_each_datapoint=False)


def show(rows):
    return None if rows is None else json.dumps(rows[:20], ensure_ascii=False, default=str) + (f" ...({len(rows)} rows)" if len(rows) > 20 else "")


def main():
    sample = json.load(open("data/sample.json"))
    client = anthropic.Anthropic(max_retries=0)  # SDK retries twice by default; Phase 0 forbids retries
    out = []
    for i, ex in enumerate(sample):
        db = ex["db_id"]
        row = {"dev_index": ex["dev_index"], "db_id": db, "question": ex["question"], "gold_sql": ex["gold_sql"],
               "model": MODEL, "effort": EFFORT, "raw_output": None, "gen_sql": None, "stop_reason": None,
               "input_tokens": None, "output_tokens": None, "api_error": None}
        try:
            row["raw_output"], row["stop_reason"], row["input_tokens"], row["output_tokens"] = generate(client, get_schema(db), ex["question"])
            row["gen_sql"] = extract_sql(row["raw_output"])
        except Exception as e:
            row["api_error"] = f"{type(e).__name__}: {e}"

        gold_rows, row["gold_error"] = execute(SPIDER_DB.format(db=db), ex["gold_sql"])
        gen_rows, row["gen_error"] = execute(SPIDER_DB.format(db=db), row["gen_sql"]) if row["gen_sql"] else (None, "no SQL generated")
        row["gold_result"], row["gen_result"] = show(gold_rows), show(gen_rows)
        row["gold_has_order_by"] = "order by" in ex["gold_sql"].lower()

        # exec_status is for analysis only; the accuracy numbers come from the official scorer.
        if row["gen_error"]:
            row["exec_status"], row["ex"], row["ts"] = "error", 0, 0
        else:
            row["exec_status"] = "empty" if len(gen_rows) == 0 else "ok"
            row["ex"] = official_match(SPIDER_DB.format(db=db), row["gen_sql"], ex["gold_sql"])
            row["ts"] = official_match(SUITE_DB.format(db=db), row["gen_sql"], ex["gold_sql"])
        print(f"[{i + 1}/{len(sample)}] {db}: status={row['exec_status']} EX={row['ex']} TS={row['ts']}")
        out.append(row)

    with open("results/phase0.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)

    n = len(out)
    errored = sum(r["exec_status"] == "error" for r in out)
    for metric in ("ex", "ts"):
        correct = sum(r[metric] for r in out)
        print(f"{metric.upper()}: correct {correct}/{n} | errored {errored}/{n} | ran but disagreed {n - correct - errored}/{n}")
    print(f"EX-correct but TS-wrong (coincidental match on the original DB): {sum(r['ex'] == 1 and r['ts'] == 0 for r in out)}")
    print(f"tokens: input {sum(r['input_tokens'] or 0 for r in out)}, output {sum(r['output_tokens'] or 0 for r in out)}")


if __name__ == "__main__":
    main()
