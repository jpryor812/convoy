#!/usr/bin/env python3
"""Open the public site's live side, and close it again on Ctrl-C.

    python3 go_live.py
    python3 go_live.py --showcase runs/phase2/20260821-232951 --port 8000

Three things, in order:

1. `serve.py --public` on this machine -- the map, the agents, the waitlist.
2. A Cloudflare quick tunnel to it, which prints a public https:// address.
3. That address, written as `live.json` to this repository's `live` branch.

The GitHub Pages site reads `live.json` (see `site/config.json`). Within a
minute or so of step 3 every visitor's page finds the server and offers to
talk to the agents; once you stop, it goes back to being the last run with a
waitlist. Start a simulation with `run_phase2.py` in another terminal whenever
you like -- the server follows the newest run and the page turns LIVE.

WHY A BRANCH. A quick tunnel's address changes every time it starts, and the
Pages site is static. Writing the address into `main` would redeploy the whole
site for every session; a one-file branch, force-pushed, changes nothing else
and keeps no history.

Ctrl-C clears `live.json` before exiting. If this process is killed hard, the
page still copes: it checks the named server and treats one that does not
answer as offline.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BRANCH = "live"
_TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def publish(server: str | None) -> None:
    """Force-push a one-file, parentless commit holding `live.json`.

    Plumbing rather than a checkout, so your working tree and current branch
    are never touched -- this runs beside whatever you are doing.
    """
    body = json.dumps({
        "server": server,
        "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=1) + "\n"

    def git(*args: str, data: str | None = None) -> str:
        return subprocess.run(
            ["git", *args], cwd=ROOT, input=data, text=True,
            capture_output=True, check=True,
        ).stdout.strip()

    blob = git("hash-object", "-w", "--stdin", data=body)
    tree = git("mktree", data=f"100644 blob {blob}\tlive.json\n")
    commit = git("commit-tree", tree, "-m",
                 f"live: {server or 'offline'}")
    git("push", "--force", "--quiet", "origin", f"{commit}:refs/heads/{BRANCH}")
    print(f"  live.json -> {server or 'offline'}")


def tunnel_answers(url: str, seconds: int) -> bool:
    """Does the tunnel answer FROM THE OUTSIDE?

    NOT through this Mac's resolver. A quick tunnel's name does not exist until
    cloudflared registers it, and if anything on this machine looked it up a
    moment too early, macOS caches the "no such host" and keeps answering it for
    minutes -- while the address works for everyone else. The first `go_live.py`
    sat in exactly that, waiting on a tunnel that was already serving.

    So: ask a public resolver (1.1.1.1) for the address, then have curl connect
    to that IP directly with the right hostname. If `dig` or `curl` is missing,
    trust cloudflared's own "registered" line, which has already been seen.
    """
    host = url.split("://", 1)[1].split("/", 1)[0]
    if not (shutil.which("dig") and shutil.which("curl")):
        return True
    deadline = time.time() + seconds
    while time.time() < deadline:
        ip = subprocess.run(["dig", "+short", "@1.1.1.1", host],
                            capture_output=True, text=True).stdout.split()
        ip = next((x for x in ip if x[:1].isdigit()), None)
        if ip:
            code = subprocess.run(
                ["curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}",
                 "--resolve", f"{host}:443:{ip}", f"{url}/status"],
                capture_output=True, text=True).stdout
            if code == "200":
                return True
        time.sleep(3)
    return False


def wait_for(url: str, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--showcase", default="showcase/20260821-232951",
                    help="the past run to show when nothing is live")
    ap.add_argument("--no-publish", action="store_true",
                    help="start the server and tunnel but do not touch live.json")
    args = ap.parse_args()

    if not shutil.which("cloudflared"):
        print("cloudflared is not installed:  brew install cloudflared")
        return 1

    children: list[subprocess.Popen] = []

    def stop(*_) -> None:
        print("\nclosing up...")
        if not args.no_publish:
            try:
                publish(None)
            except subprocess.CalledProcessError as exc:
                print(f"  could not clear live.json: {exc.stderr.strip()}")
        for p in children:
            p.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    # Keep the machine awake for as long as this runs. PHASE8 §8: a sleeping
    # laptop took eight wall hours to reach simulated hour three.
    if shutil.which("caffeinate"):
        children.append(subprocess.Popen(
            ["caffeinate", "-ims", "-w", str(os.getpid())]))

    print(f"starting the server on port {args.port}...")
    children.append(subprocess.Popen(
        [sys.executable, "serve.py", "--public", "--trust-proxy",
         "--host", "127.0.0.1", "--port", str(args.port),
         "--showcase", args.showcase],
        cwd=ROOT,
    ))
    if not wait_for(f"http://127.0.0.1:{args.port}/status", 60):
        print("the server did not come up; see its output above")
        stop()

    print("opening the tunnel...")
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate",
         "--url", f"http://127.0.0.1:{args.port}"],
        stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True,
    )
    children.append(tunnel)
    # The address comes first, then -- separately -- the line saying Cloudflare
    # has accepted the connection. Only the second means the address will work.
    url, registered = None, False
    deadline = time.time() + 90
    while time.time() < deadline and not (url and registered):
        line = tunnel.stderr.readline()
        if not line:
            break
        m = _TUNNEL_RE.search(line)
        if m and url is None:
            url = m.group(0)
            print(f"tunnel address: {url}")
        if "Registered tunnel connection" in line:
            registered = True
    if url is None or not registered:
        print("cloudflared did not finish connecting within 90 seconds; try again")
        stop()

    # Publishing before the address answers would send every visitor's page
    # to a dead link, so check -- from the outside, see `tunnel_answers`.
    print("checking it answers from the internet...")
    if not tunnel_answers(url, 90):
        print("the tunnel never answered; try again")
        stop()

    if not args.no_publish:
        publish(url)

    print(f"""
LIVE.
  this session : {url}
  the site     : https://jpryor812.github.io/convoy/  (finds it within a minute)

Start a simulation in another terminal whenever you like; the site turns LIVE
when its log starts moving. Ctrl-C here to close everything.
""")
    # Keep cloudflared's pipe drained so it never blocks on a full buffer.
    for _ in tunnel.stderr:
        pass
    stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
