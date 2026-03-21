"""
Fetch, set, or tail logs for Railway services.

Usage:
    python3 scripts/get_railway_vars.py [service]                 # list all vars (masked)
    python3 scripts/get_railway_vars.py [service] --raw KEY       # print one value unmasked
    python3 scripts/get_railway_vars.py [service] --set KEY VALUE # upsert a variable
    python3 scripts/get_railway_vars.py [service] --logs [N]      # show last N log lines (default 100)

    service: ghost (default) | email-worker

Credentials are loaded from .env (RAILWAY_TOKEN). Never hardcoded.
"""
import json
import sys
import os
import httpx
from pathlib import Path

# ── Credentials ────────────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

_load_env()

token = os.environ.get("RAILWAY_TOKEN")
if not token:
    print("Error: RAILWAY_TOKEN not set. Add it to your .env file.")
    print("Get a token at: https://railway.app/account/tokens")
    sys.exit(1)

# ── Service map ────────────────────────────────────────────────
PROJECT_ID     = "752fdaea-fd96-4521-bec6-b7d5ef451270"
ENVIRONMENT_ID = "c9dfebe4-097a-4151-be37-2b1fcd414e74"
SERVICES = {
    "ghost":        "0daf496c-e14f-41d4-b89b-3624a778c99d",
    "email-worker": "15b13afb-8515-49e9-ab38-7e138069064f",
}

# Parse args: [service] [--raw KEY] [--set KEY VALUE] [--logs [N]]
args = sys.argv[1:]
raw_key = None
set_key = None
set_val = None
show_logs = False
log_lines = 100

if "--raw" in args:
    idx = args.index("--raw")
    raw_key = args[idx + 1] if idx + 1 < len(args) else None
    args = [a for a in args if a not in ("--raw", raw_key)]

if "--set" in args:
    idx = args.index("--set")
    set_key = args[idx + 1] if idx + 1 < len(args) else None
    set_val = args[idx + 2] if idx + 2 < len(args) else None
    args = [a for a in args if a not in ("--set", set_key, set_val)]

if "--logs" in args:
    show_logs = True
    idx = args.index("--logs")
    # optional numeric argument after --logs
    if idx + 1 < len(args) and args[idx + 1].isdigit():
        log_lines = int(args[idx + 1])
        args = [a for a in args if a not in ("--logs", args[idx + 1])]
    else:
        args = [a for a in args if a != "--logs"]

service_name = args[0] if args else "ghost"
service_id   = SERVICES.get(service_name)
if not service_id:
    print(f"Unknown service '{service_name}'. Valid options: {', '.join(SERVICES)}")
    sys.exit(1)

# ── Upsert ─────────────────────────────────────────────────────
if set_key and set_val is not None:
    mutation = """
    mutation UpsertVar($input: VariableUpsertInput!) {
      variableUpsert(input: $input)
    }
    """
    r = httpx.post(
        "https://backboard.railway.app/graphql/v2",
        json={
            "query": mutation,
            "variables": {
                "input": {
                    "projectId": PROJECT_ID,
                    "environmentId": ENVIRONMENT_ID,
                    "serviceId": service_id,
                    "name": set_key,
                    "value": set_val,
                }
            }
        },
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = r.json()
    if "errors" in data:
        print("GraphQL errors:", json.dumps(data["errors"], indent=2))
        sys.exit(1)
    masked = set_val[:8] + "..." + set_val[-4:] if len(set_val) > 12 else set_val
    print(f"✓  {set_key} set on {service_name} service  ({masked})")
    sys.exit(0)

# ── Logs ───────────────────────────────────────────────────────
if show_logs:
    # Step 1: get latest deployment id
    deploy_q = """
    query Deploys($serviceId: String!, $environmentId: String!) {
      deployments(
        input: { serviceId: $serviceId, environmentId: $environmentId }
        last: 1
      ) {
        edges { node { id status createdAt } }
      }
    }
    """
    r = httpx.post(
        "https://backboard.railway.app/graphql/v2",
        json={"query": deploy_q, "variables": {
            "serviceId": service_id,
            "environmentId": ENVIRONMENT_ID,
        }},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    data = r.json()
    if "errors" in data:
        print("GraphQL errors:", json.dumps(data["errors"], indent=2))
        sys.exit(1)
    edges = (data.get("data") or {}).get("deployments", {}).get("edges", [])
    if not edges:
        print(f"No deployments found for {service_name}.")
        sys.exit(1)
    deploy = edges[0]["node"]
    deploy_id = deploy["id"]
    print(f"{service_name} — deployment {deploy_id} [{deploy['status']}] created {deploy['createdAt']}\n")

    # Step 2: fetch logs
    logs_q = """
    query Logs($deploymentId: String!) {
      deploymentLogs(deploymentId: $deploymentId) {
        timestamp
        message
        severity
      }
    }
    """
    r2 = httpx.post(
        "https://backboard.railway.app/graphql/v2",
        json={"query": logs_q, "variables": {"deploymentId": deploy_id}},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        timeout=30,
    )
    log_data = r2.json()
    if "errors" in log_data:
        # deploymentLogs may not exist on all plans — try plugin logs endpoint
        print("deploymentLogs query failed:")
        print(json.dumps(log_data["errors"], indent=2))
        sys.exit(1)
    logs = (log_data.get("data") or {}).get("deploymentLogs", [])
    if not logs:
        print("No logs returned — the deployment may still be starting, or logs are not available via API on this plan.")
        sys.exit(0)
    for entry in logs[-log_lines:]:
        ts  = entry.get("timestamp", "")[:19].replace("T", " ")
        sev = entry.get("severity", "INFO")
        msg = entry.get("message", "")
        print(f"[{ts}] [{sev:5}] {msg}")
    sys.exit(0)

# ── Query ──────────────────────────────────────────────────────
query = """
query GetVariables($projectId: String!, $environmentId: String!, $serviceId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
}
"""

r = httpx.post(
    "https://backboard.railway.app/graphql/v2",
    json={
        "query": query,
        "variables": {
            "projectId": PROJECT_ID,
            "environmentId": ENVIRONMENT_ID,
            "serviceId": service_id,
        }
    },
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    },
    timeout=15,
)
data = r.json()

if "errors" in data:
    print("GraphQL errors:", json.dumps(data["errors"], indent=2))
    sys.exit(1)

variables = data.get("data", {}).get("variables", {})

if raw_key:
    val = variables.get(raw_key)
    if val is None:
        print(f"Key '{raw_key}' not found in {service_name} service.")
        sys.exit(1)
    print(val)
    sys.exit(0)

print(f"\n{service_name} service — {len(variables)} variables (caring-alignment / production):\n")
for k in sorted(variables.keys()):
    v = variables[k]
    if v:
        masked = v[:8] + "..." + v[-4:] if len(v) > 12 else v
        print(f"  {k}: {masked}")
    else:
        print(f"  {k}: (empty)")
