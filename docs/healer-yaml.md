# healer.yaml (v1)

The application descriptor an administrator fills in (via the dashboard
wizard, or by pasting/uploading a YAML file) to tell Healer what an
application is, where its code lives, and how to run and health-check it.
Schema: [`app/schemas/healer_yaml.py`](../services/control-plane/app/schemas/healer_yaml.py).
Parser: [`app/domain/healer_yaml.py`](../services/control-plane/app/domain/healer_yaml.py).

Saving and validating a healer.yaml (`POST /applications`,
`POST /applications/{id}/validate`) never deploys anything, runs
migrations, starts a process, or touches Nginx — see
[`docs/app-validation.md`](app-validation.md) for exactly what each field's
validation actually checks and how.

## Windows — `windows-waitress-service`

```yaml
version: 1
name: rit-academic-erp
adapter: windows-waitress-service
server_id: 2d11fe1c-47ac-4fd3-813e-6e5ad169092c

source:
  type: folder          # or: git
  location: C:\apps\erp
  # ref: main            # only meaningful when type: git

windows:
  python_executable: C:\apps\erp\venv\Scripts\python.exe
  requirements_file: requirements.txt   # relative to source.location
  manage_py: manage.py                  # relative to source.location
  wsgi_module: erp.wsgi
  settings_module: erp.settings.production

health:
  path: /health/
  interval_seconds: 10
  timeout_seconds: 5
  healthy_threshold: 2
  unhealthy_threshold: 3

ports:
  start: 9034
  end: 9039

domain:
  hostname: erp.ritrjpm.edu.in
  cert_path: /etc/healer/certs/ritrjpm.edu.in.crt
  key_path: /etc/healer/certs/ritrjpm.edu.in.key

secrets:
  - DB_PASSWORD
  - DJANGO_SECRET_KEY
```

## Linux — `linux-docker`

```yaml
version: 1
name: internal-api
adapter: linux-docker
server_id: 469f8670-728e-410e-8a2f-97fa99de06c4

source:
  type: dockerfile      # or: image
  location: ./Dockerfile

linux:
  internal_port: 8000

health:
  path: /healthz

ports:
  start: 9100
  end: 9104

domain:
  hostname: api.internal.example.com
```

## Fields

| Field | Meaning |
|---|---|
| `version` | Always `1` for this schema. A breaking change to this format gets a `version: 2` and a new schema class, the same versioning rule as `protocols/`. |
| `adapter` | `windows-waitress-service` or `linux-docker` — the same vocabulary as `AdapterType` and the Agent's own reported capabilities. |
| `server_id` | The registered server this application targets. Must actually run an Agent whose reported capabilities include this adapter. |
| `source` | Where the code (or image) comes from. `folder`/`git` for Windows; `dockerfile`/`image` for Linux. Image sources require `repository@sha256:<64 hex digits>`. |
| `windows` / `linux` | Adapter-specific fields — exactly one is present, matching `adapter`. |
| `health` | HTTP health check path + timing thresholds. |
| `ports` | The port range Healer may allocate instances into on `server_id` (allocation itself is Phase 9). |
| `domain` | The public hostname, and optionally existing CRT/KEY file paths (validated through the Gateway Manager — never generated or uploaded). |
| `secrets` | Names of secret keys this application needs. Validated for existence only — values are never returned by any API. |
