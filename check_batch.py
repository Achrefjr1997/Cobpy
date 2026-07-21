import httpx

resp = httpx.get("http://localhost:8000/api/migrations/batch/552034f8047d4fca85d7223bcc3c3a06")
d = resp.json()
print("status:", d["status"])
for k, v in d.get("program_results", {}).items():
    print(f"  {k}: verdict={v.get('verdict')}, error={v.get('error')}")
if d["status"] in ("completed", "partial"):
    print("\nIntegration issues:", d.get("integration_issues", []))
