#!/usr/bin/env python3
"""Project Dashboard v3 — Fast scanning with detailed project views and links."""

import json
import os
import re
import subprocess
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 8766
PROJECTS_DIR = "/Users/tko/Development"
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


def load_data():
    default = {"social_posts": [], "expenses": [], "projects": {}, "waitlist": [], "waitlist_count": 0}
    if not os.path.exists(DATA_FILE):
        return default
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        for k in default:
            if k not in data:
                data[k] = default[k]
        return data
    except:
        return default


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def run_cmd(cmd, cwd=None, timeout=2):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip()
    except:
        pass
    return None


def scan_projects():
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        return projects
    
    # Exclude non-projects
    skip_dirs = {'hermes-matrix-dashboard', 'venv', 'node_modules', '.git', '__pycache__'}
    
    for name in sorted(os.listdir(PROJECTS_DIR)):
        path = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(path) or name.startswith('.') or name.startswith('__') or name in skip_dirs:
            continue

        p = {
            "name": name,
            "path": path,
            "framework": "unknown",
            "status": "unknown",
            "url": None,
            "git_branch": None,
            "git_last_commit_msg": None,
            "git_last_commit_date": None,
            "total_files": 0,
        }

        # Fast git metadata check
        branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        if branch:
            p["git_branch"] = branch

        lc = run_cmd(["git", "log", "-1", "--format=%s|%ci"], cwd=path)
        if lc and "|" in lc:
            parts = lc.split("|", 1)
            p["git_last_commit_msg"] = parts[0]
            p["git_last_commit_date"] = parts[1]

        # Quick file count (limit depth to 2 to avoid scanning huge node_modules)
        try:
            file_count = 0
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', '__pycache__', '.next', 'dist', 'build', '.output')]
                file_count += len(files)
                if file_count > 500:  # Cap count to keep it fast
                    break
            p["total_files"] = file_count
        except:
            p["total_files"] = 0

        # Framework detection
        if os.path.exists(os.path.join(path, "nuxt.config.ts")) or os.path.exists(os.path.join(path, "nuxt.config.js")):
            p["framework"] = "Nuxt 3"
        elif os.path.exists(os.path.join(path, "package.json")):
            p["framework"] = "Node.js"
        elif any(f.endswith('.py') for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))):
            p["framework"] = "Python"

        # Check PROJECT.md for status/url
        proj_md = os.path.join(path, "PROJECT.md")
        if os.path.exists(proj_md):
            try:
                content = open(proj_md).read().lower()
                if "validation" in content: p["status"] = "validation"
                elif "building" in content: p["status"] = "building"
                elif "live" in content: p["status"] = "live"
                urls = re.findall(r'https?://[^\s\)]+', content)
                if urls: p["url"] = urls[0]
            except:
                pass

        projects.append(p)
    return projects


def get_tweet_metrics(tweet_id):
    """Fetch metrics for a specific tweet."""
    if not tweet_id:
        return None
    out = run_cmd(["xurl", "read", str(tweet_id)], timeout=3)
    if out:
        try:
            data = json.loads(out)
            metrics = data.get("data", {}).get("public_metrics", {})
            return {
                "likes": metrics.get("like_count", 0),
                "retweets": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
                "quotes": metrics.get("quote_count", 0),
                "impressions": metrics.get("impression_count", 0),
            }
        except:
            pass
    return None


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/api/projects":
            self.send_json({"projects": scan_projects()})
            return

        if path == "/api/data":
            self.send_json(load_data())
            return

        if path == "/api/project/detail":
            name = query.get("name", [""])[0]
            data = load_data()
            
            # Find in scanned projects or project metadata
            all_projs = scan_projects()
            proj = next((p for p in all_projs if p["name"] == name), None)
            
            proj_meta = data.get("projects", {}).get(name, {})
            
            if not proj:
                # If directory name doesn't match, look up by metadata directory field
                for k, v in data.get("projects", {}).items():
                    if v.get("directory") == name or k == name:
                        proj_meta = v
                        proj = next((p for p in all_projs if p["name"] == v.get("directory")), None)
                        break

            if not proj and not proj_meta:
                self.send_json({"error": "Not found", "name": name}, 404)
                return

            base = proj or {"name": name, "framework": "unknown", "status": "unknown"}
            
            posts = [p for p in data.get("social_posts", []) if p.get("project") == name or p.get("project") == proj_meta.get("directory")]
            
            detail = {
                **base,
                "display_name": proj_meta.get("display_name", base.get("name")),
                "goal": proj_meta.get("goal", 50),
                "github": proj_meta.get("github"),
                "cloudflare": proj_meta.get("cloudflare"),
                "niche": proj_meta.get("niche"),
                "expenses": [e for e in data.get("expenses", []) if e.get("project") == name or e.get("project") == proj_meta.get("directory")],
                "total_spend": sum(e.get("cost", 0) for e in data.get("expenses", []) if e.get("project") == name or e.get("project") == proj_meta.get("directory")),
                "social_posts": posts,
                "waitlist_count": data.get("waitlist_count", 0),
            }
            self.send_json(detail)
            return

        if path == "/api/twitter/engagement":
            data = load_data()
            engagement = []
            for post in data.get("social_posts", []):
                if post.get("tweet_id") and post.get("posted"):
                    metrics = get_tweet_metrics(post["tweet_id"])
                    if metrics:
                        engagement.append({
                            "tweet_id": post["tweet_id"],
                            "text": post["text"][:60] + "..." if len(post.get("text","")) > 60 else post.get("text",""),
                            **metrics,
                        })
            self.send_json({"engagement": engagement})
            return

        if path == "/" or path == "":
            path = "/index.html"

        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path.lstrip("/"))
        if os.path.isfile(file_path):
            self.send_file(file_path)
        else:
            self.send_json({"error": f"Not found: {path}"}, 404)

    def send_json(self, data, status=200):
        resp = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp)

    def send_file(self, path):
        ct = "application/octet-stream"
        if path.endswith(".html"): ct = "text/html"
        elif path.endswith(".js"): ct = "application/javascript"
        elif path.endswith(".css"): ct = "text/css"
        with open(path, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Dashboard running on http://127.0.0.1:{PORT}")
    server.serve_forever()
