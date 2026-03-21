import json
import urllib.request
import sys
import os
from pathlib import Path

# Load credentials from .env (never hardcode)
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
project_id = "752fdaea-fd96-4521-bec6-b7d5ef451270"
environment_id = "c9dfebe4-097a-4151-be37-2b1fcd414e74"

query = """
query GetVariables($projectId: String!, $environmentId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId)
}
"""

req = urllib.request.Request(
    "https://backboard.railway.app/graphql/v2",
    data=json.dumps({
        "query": query,
        "variables": {
            "projectId": project_id,
            "environmentId": environment_id
        }
    }).encode(),
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
    }
)

resp = urllib.request.urlopen(req)
data = json.loads(resp.read())

if "errors" in data:
    print("GraphQL errors:", json.dumps(data["errors"], indent=2))
    sys.exit(1)

variables = data.get("data", {}).get("variables", {})
print(f"Found {len(variables)} variables in caring-alignment/production:\n")
for k in sorted(variables.keys()):
    v = variables[k]
    # Mask the value but show enough to confirm it's set
    if v:
        masked = v[:8] + "..." + v[-4:] if len(v) > 12 else "(short)"
        print(f"  {k}: {masked}")
    else:
        print(f"  {k}: (empty)")
