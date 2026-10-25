"""Portable OpenEgiz + VentObserve launcher; Python stdlib, no make required."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def credentials(path):
    """Preserve existing credentials; never print them."""
    if not path.exists():
        values = {"OPENEGIZ_BIND": "127.0.0.1", "OPENEGIZ_PUBLIC_HOST": "localhost",
                  "GRAFANA_PORT": "3000", "DITTO_PORT": "8080", "EXTENDED_API_PORT": "8085",
                  "UNITY_PORT": "8090", "INFLUXDB_PORT": "8086", "MQTT_PORT": "1883"}
        for key in ("GRAFANA_ADMIN_PASSWORD", "DITTO_PASSWORD", "DITTO_DEVOPS_PASSWORD",
                    "INFLUXDB_ADMIN_PASSWORD", "INFLUXDB_TOKEN"):
            values[key] = secrets.token_hex(20)
        for key, user, password_key in (("DITTO_BASIC_AUTH", "ditto", "DITTO_PASSWORD"),
                                        ("DITTO_DEVOPS_BASIC_AUTH", "devops", "DITTO_DEVOPS_PASSWORD")):
            values[key] = base64.b64encode(f"{user}:{values[password_key]}".encode()).decode()
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Local generated credentials. Do not commit.\n")
            handle.writelines(f"{key}={value}\n" for key, value in values.items())
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    for key in ("DITTO_PASSWORD", "DITTO_DEVOPS_PASSWORD", "GRAFANA_ADMIN_PASSWORD", "INFLUXDB_TOKEN"):
        if not values.get(key):
            raise RuntimeError(f"Existing .env is missing {key}; restore the original credentials")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform-dir", type=Path, default=Path(os.getenv("OPENEGIZ_DIR", ROOT/"openegiz")))
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--stop", action="store_true", help="Stop this stack, preserving volumes")
    args = parser.parse_args()
    platform = args.platform_dir.resolve()
    compose_file = platform/"deploy/compose/docker-compose.yml"
    if not compose_file.is_file():
        raise RuntimeError("OpenEgiz Compose file not found; specify --platform-dir")
    if not args.stop:
        import zipfile
        for name in ('ertis-opentwins-app.zip','ertis-unity-panel.zip'):
            plugin = platform/'vendor/grafana-plugins'/name
            if not plugin.is_file() or not zipfile.is_zipfile(plugin):
                raise RuntimeError(f'Missing or invalid required Grafana plugin: {plugin}. Extract the complete release archive.')
    config = credentials(platform/"deploy/compose/.env")
    env = {**os.environ, "VENTOBSERVE_DIR": ROOT.as_posix()}
    env.setdefault('COMPOSE_PROGRESS','plain')
    # Desktop Bake on Windows can interpret a remote Git context as C:\...\https:.
    # The regular Compose builder preserves the upstream pinned Git context.
    if os.name=='nt':env['COMPOSE_BAKE']='false'
    env["OPENEGIZ_DIR"] = str(platform)
    for key in config:
        env.pop(key, None)
    compose = ["docker", "compose", "--env-file", str(platform/"deploy/compose/.env"),
               "-f", str(compose_file), "-f", str(ROOT/"integration/compose.yml")]
    def run(*parts, capture=False, timeout=2400):
        return subprocess.run([*compose, *parts], cwd=platform, env=env, check=True,
                              capture_output=capture, text=True, timeout=timeout)
    run("config", "--quiet")
    if args.stop:
        run("stop")
        print("Stopped; data volumes preserved.")
        return
    if args.check_only:
        print("PASS: Compose configuration valid. Engine and end-to-end not tested.")
        return
    from prepare_extended_api import prepare
    prepare(ROOT)
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True, env=env, timeout=20)
    started = time.monotonic()
    run("up", "-d", "--build", "--wait", "--wait-timeout", "900")
    init = run("ps", "-a", "-q", "init", capture=True).stdout.strip()
    if not init:
        raise RuntimeError("OpenEgiz init container not found")
    result = subprocess.run(["docker", "wait", init], capture_output=True, text=True,
                            check=True, timeout=900, env=env)
    if result.stdout.strip() != "0":
        raise RuntimeError("OpenEgiz init failed. Inspect compose logs init.")
    deadline = time.monotonic()+180
    while True:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=5) as response:
                state = json.load(response)
            if state["connection"]["source"] != "Ditto" or time.time()-state["wall_time"] > 15:
                raise RuntimeError("No fresh platform snapshot")
            break
        except (OSError, ValueError, KeyError, RuntimeError):
            if time.monotonic() >= deadline:
                raise RuntimeError("No fresh Ditto snapshot in 180s. Inspect ventobserve logs.") from None
            time.sleep(2)
    print(f"READY in {time.monotonic()-started:.0f}s: http://localhost:8765 (Eclipse Ditto)")
    print("Grafana: http://localhost:"+config.get("GRAFANA_PORT", "3000"))
    print("Credentials stored locally in OpenEgiz deploy/compose/.env; never publish them.")
    subprocess.run([sys.executable, str(ROOT/"integration/smoke-network-platform.py")],
                   check=True, cwd=ROOT, env=env, timeout=240)
    # Docker Desktop bind-mount changes may not trigger Grafana's file watcher.
    auth = base64.b64encode(('admin:'+config['GRAFANA_ADMIN_PASSWORD']).encode()).decode()
    request = urllib.request.Request(
        'http://127.0.0.1:'+config.get('GRAFANA_PORT','3000')+'/api/admin/provisioning/dashboards/reload',
        data=b'{}', headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30) as response:
        if response.status != 200:raise RuntimeError('Grafana provisioning reload failed')
    # Allow a first sample and a flush on a clean installation.
    for attempt in range(6):
        result = subprocess.run([sys.executable,str(ROOT/'integration/smoke-history.py')],
                                cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
        if result.returncode == 0:
            print('PASS: all four Grafana panels contain fresh Ditto history')
            break
        if attempt == 5:raise RuntimeError('Grafana history check failed; inspect docs/dashboard-check.json and telegraf logs')
        time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"START FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
