import argparse
import csv
import io
import json
import os
import threading
import time
import copy
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit
from .model import Twin
from .platform import Platform

BASE = Path(__file__).parent / "static"


class Runtime:
    def __init__(self, mode="local", model="legacy"):
        self.mode = mode
        self.lock = threading.RLock()
        self.model = model
        if model == 'network':
            from .network_twin import NetworkTwin
            self.twin = NetworkTwin()
        else:
            self.twin = Twin()
        self.simulation_error = None
        self.platform = Platform(model=model) if mode == "platform" else None
        self.running = True

    def loop(self):
        next_setup = 0
        while self.running:
            start = time.monotonic()
            with self.lock:
                try:
                    self.twin.tick(self.twin.speed)
                    self.simulation_error = None
                except (ValueError, ArithmeticError) as exc:
                    self.simulation_error = str(exc)
                    time.sleep(.5)
                    continue
                self.twin.snapshot["wall_time"] = time.time()
                snapshot = {**self.twin.snapshot, 'series': copy.deepcopy(self.twin.history[-160:])}
            if self.platform:
                try:
                    if not self.platform.client:
                        if time.monotonic() >= next_setup:
                            self.platform.setup()
                    if self.platform.client:
                        self.platform.publish(snapshot)
                except Exception as exc:
                    self.platform.status = "error"
                    # Avoid disclosing credential-bearing URLs or HTTP headers.
                    self.platform.last_error = type(exc).__name__
                    next_setup = time.monotonic()+5
            time.sleep(max(.05, 1-(time.monotonic()-start)))

    def health(self):
        return {"mode": self.mode, "model": self.model, "simulation_error": self.simulation_error, "source": "Ditto" if self.platform else "local simulator",
                "platform": self.platform.status if self.platform else "disabled",
                "last_error": self.platform.last_error if self.platform else None,
                "last_read": self.platform.last_read if self.platform else None,
                "last_publish": self.platform.last_publish if self.platform else None}


def handler_for(runtime):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, body, status=200, mime="application/json; charset=utf-8", attachment=None):
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if mime.startswith("application/json") else body
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'self' http://localhost:3000 http://127.0.0.1:3000")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == "/api/health":
                    return self.respond(runtime.health())
                if path == "/api/state":
                    if runtime.simulation_error:
                        return self.respond({'error':runtime.simulation_error},503)
                    if runtime.platform:
                        state = runtime.platform.read_snapshot()
                        if time.time()-state.get("wall_time", 0)>15:
                            raise RuntimeError("Ditto snapshot is stale")
                    else:
                        with runtime.lock:
                            state = json.loads(json.dumps(runtime.twin.snapshot))
                            state['series']=copy.deepcopy(runtime.twin.history[-160:])
                    return self.respond({**state, "connection": runtime.health()})
                if path == '/api/reference':
                    from .reference import run
                    return self.respond(run())
                if path == '/api/evaluation':
                    report=Path(__file__).resolve().parent.parent/('docs/network-evaluation.json' if runtime.model=='network' else 'docs/evaluation.json')
                    data=json.loads(report.read_text(encoding='utf-8'))
                    if data.get('model_signature')!=type(runtime.twin).model_signature():
                        return self.respond({'error':'Результат относится к другой версии модели; выполните python -m app.evaluation'},409)
                    return self.respond({k:v for k,v in data.items() if k not in ('records','groups')})
                if path in ('/api/utility','/api/utility.json'):
                    import hashlib
                    root=Path(__file__).resolve().parent.parent
                    data=json.loads((root/'docs/sensor-utility.json').read_text(encoding='utf8'))
                    if data.get('model_signature')!=type(runtime.twin).model_signature() or data.get('study_signature')!=hashlib.sha256((root/'app/sensor_utility.py').read_bytes()).hexdigest():
                        return self.respond({'error':'Отчёт относится к другой версии; выполните python -m app.sensor_utility'},409)
                    if path.endswith('.json'):return self.respond(data,attachment='sensor-utility.json')
                    return self.respond({k:v for k,v in data.items() if k not in ('records','examples')})
                if path in ("/api/export.json", "/api/history.csv"):
                    # Experiment audit exports are local simulator records, labelled explicitly.
                    with runtime.lock:
                        data = {"source": "local simulation audit", "mode": runtime.mode,
                                "state": runtime.twin.snapshot, "history": runtime.twin.history}
                        if path.endswith(".json"):
                            data["experiment"]=runtime.twin.export_experiment()
                            return self.respond(data, attachment="ventobserve-experiment.json")
                        buf = io.StringIO()
                        w = csv.writer(buf)
                        if runtime.model=='network':
                            w.writerow(['time_s','node','truth_pct','low_pct','high_pct'])
                            for row in data['history']:
                                for node, val in row['gas'].items():
                                    w.writerow([row['t'],node,val,row['estimate'][node]['low'],row['estimate'][node]['high']])
                            return self.respond(buf.getvalue().encode('utf-8-sig'),mime='text/csv; charset=utf-8',attachment='ventobserve-network.csv')
                        w.writerow(["time_s", "truth_A_pct", "truth_B_pct", "A_low", "A_high", "B_low", "B_high"])
                        for row in data["history"]:
                            e = row["estimate"]
                            w.writerow([row["t"], row["ca"], row["cb"], e["ca"]["low"], e["ca"]["high"], e["cb"]["low"], e["cb"]["high"]])
                    return self.respond(buf.getvalue().encode("utf-8-sig"), mime="text/csv; charset=utf-8", attachment="ventobserve-history.csv")
                files = {"/": ("index.html", "text/html"), "/style.css": ("style.css", "text/css"),
                         "/app.js": ("app.js", "application/javascript")}
                if runtime.model=='network':
                    files['/']=('network.html','text/html')
                    files['/app.js']=('network.js','application/javascript')
                if path not in files:
                    return self.respond({"error": "not found"}, 404)
                name, mime = files[path]
                return self.respond((BASE/name).read_bytes(), mime=mime+"; charset=utf-8")
            except Exception as exc:
                return self.respond({"error": "Источник данных недоступен", "type": type(exc).__name__}, 503)

        def do_POST(self):
            if self.path not in ("/api/command","/api/replay"):
                return self.respond({"error": "not found"}, 404)
            # Bound, same-origin local application. Disallow cross-origin mutations.
            origin = self.headers.get("Origin")
            if origin and origin != "http://"+self.headers.get("Host", ""):
                return self.respond({"error": "origin rejected"}, 403)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= (2*1024*1024 if self.path=="/api/replay" else 4096):
                    raise ValueError("Некорректный размер запроса")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Ожидается объект")
                if self.path=="/api/replay":
                    replacement=type(runtime.twin).replay(data.get("experiment",data))
                    with runtime.lock:
                        runtime.twin=replacement
                        runtime.simulation_error = None
                        runtime.twin.snapshot["wall_time"]=time.time()
                    return self.respond({"accepted":True,"experiment_id":replacement.experiment_id,"revision":replacement.revision,"mode":runtime.mode})
                with runtime.lock:
                    runtime.twin.command(data)
                    runtime.simulation_error = None
                    receipt = {"accepted": True, "mode": runtime.mode, "experiment_id": runtime.twin.experiment_id, "revision": runtime.twin.revision}
                return self.respond(receipt)
            except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
                return self.respond({"error": str(exc)}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--mode", choices=["local", "platform"], default=os.getenv("VENT_MODE", "local"))
    parser.add_argument('--model',choices=['network','legacy'],default='network')
    args = parser.parse_args()
    runtime = Runtime(args.mode,args.model)
    threading.Thread(target=runtime.loop, daemon=True).start()
    print(f"VentObserve: http://{args.host}:{args.port} | {args.mode}", flush=True)
    server = ThreadingHTTPServer((args.host, args.port), handler_for(runtime))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        runtime.running = False
        server.server_close()
        if runtime.platform:
            runtime.platform.close()


if __name__ == "__main__":
    main()
