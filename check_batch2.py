import httpx, time

time.sleep(60)
print("polling...")
r = httpx.get("http://localhost:8000/api/migrations/batch/552034f8047d4fca85d7223bcc3c3a06")
d = r.json()
print("status:", d["status"])
for k, v in d.get("program_results", {}).items():
    print(f"  {k}: verdict={v.get('verdict')}")
print("issues:", d.get("integration_issues", "n/a"))
