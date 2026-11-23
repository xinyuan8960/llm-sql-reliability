"""Local server for blind adjudication. Stdlib only.

Run from the repo root:  python src/review_server.py   then open http://127.0.0.1:8765

The key file is read here only to assign each item to a tranche:
  A = rows from questions where the two arms disagreed
  B = rows from questions where both arms were wrong
The browser receives the blind columns plus the tranche letter. Arm and verdict never leave this process.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
PORT = 8765
BLIND = f"results/adjudication_blind_n{N}.csv"
KEY = f"results/adjudication_key_n{N}.csv"
LABELS = "results/labels.csv"
LABEL_COLS = ["item_id", "label", "note", "timestamp"]
ALLOWED = {"correct", "model_error", "evidence_error", "gold_error", "ambiguous", "skip"}
HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.html")


def load_items():
    blind = list(csv.DictReader(open(BLIND)))
    key = list(csv.DictReader(open(KEY)))
    verdicts = {}
    for k in key:
        verdicts.setdefault(k["question_id"], set()).add(k["ex"])
    tranche = {}
    for k in key:
        v = verdicts[k["question_id"]]
        assert v in ({"0", "1"}, {"0"}), f"unexpected verdicts for question {k['question_id']}: {v}"
        tranche[k["item_id"]] = "A" if v == {"0", "1"} else "B"
    fields = ["item_id", "question", "evidence", "gold_sql", "generated_sql", "gold_result", "generated_result"]
    items = [{**{f: r[f] for f in fields}, "tranche": tranche[r["item_id"]]} for r in blind]
    # Keep the blind file's shuffled order within each tranche; A first.
    return [i for i in items if i["tranche"] == "A"] + [i for i in items if i["tranche"] == "B"]


def load_labels():
    latest = {}
    if os.path.exists(LABELS):
        for r in csv.DictReader(open(LABELS)):
            latest[r["item_id"]] = r  # file is append-only, so the last row per item wins
    return latest


ITEMS = load_items()
ITEM_IDS = {i["item_id"] for i in ITEMS}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send(200, open(HTML, "rb").read(), "text/html")
        elif self.path == "/api/items":
            self.send(200, json.dumps({"items": ITEMS, "labels": load_labels()}))
        else:
            self.send(404, '{"error": "not found"}')

    def do_POST(self):
        if self.path != "/api/label":
            return self.send(404, '{"error": "not found"}')
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        item_id, label = body.get("item_id"), body.get("label")
        note = " ".join(str(body.get("note", "")).split())  # one line
        if item_id not in ITEM_IDS or label not in ALLOWED:
            return self.send(400, json.dumps({"error": "bad item_id or label"}))
        row = {"item_id": item_id, "label": label, "note": note,
               "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        new_file = not os.path.exists(LABELS) or os.path.getsize(LABELS) == 0
        with open(LABELS, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LABEL_COLS)
            if new_file:
                w.writeheader()
            w.writerow(row)
            f.flush()
            os.fsync(f.fileno())
        self.send(200, json.dumps(row))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    a = sum(i["tranche"] == "A" for i in ITEMS)
    print(f"{len(ITEMS)} items (tranche A: {a}, tranche B: {len(ITEMS) - a}) | labels -> {LABELS}")
    print(f"open http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
