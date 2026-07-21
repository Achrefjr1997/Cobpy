import httpx, time, json

for i in range(60):
    resp = httpx.get("http://localhost:8000/api/migrations/batch/552034f8047d4fca85d7223bcc3c3a06")
    data = resp.json()
    status = data["status"]
    results = data.get("program_results", {})
    completed = sum(1 for p in results.values() if isinstance(p, dict) and p.get("verdict"))
    total = len(data.get("migration_order", []))
    print(f"[{i}] status={status}, completed={completed}/{total}")

    if status in ("completed", "partial", "cancelled"):
        for pid, r in results.items():
            if isinstance(r, dict):
                print(f"  {pid}: verdict={r.get('verdict')}, error={r.get('error')}")
        break
    time.sleep(10)
