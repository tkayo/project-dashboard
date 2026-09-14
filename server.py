#!/usr/bin/env python3
"""Project Dashboard v2 — with detail views and Chart.js integration."""

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


def run_cmd(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            return r.stdout.strip()
    except:
        pass
    return None


def scan_projects():
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        return projects
    for name in sorted(os.listdir(PROJECTS_DIR)):
        path = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(path) or name.startswith('.') or name.startswith('__'):
            continue
        if name in ('hermes-matrix-dashboard', 'project-dashboard', 'venv', 'node_modules'):
            continue

        p = {"name": name, "path": path, "framework": "unknown", "status": "unknown",
             "url": None, "git_last_commit_msg": None, "git_last_commit_date": None,
             "total_files": 0, "file_counts": {}}

        branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        if branch:
            p["git_branch"] = branch

        lc = run_cmd(["git", "log", "-1", "--format=%H|%s|%ci"], cwd=path)
        if lc:
            parts = lc.split("|", 2)
            if len(parts) == 3:
                p["git_last_commit_msg"] = parts[1]
                p["git_last_commit_date"] = parts[2]

        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ('node_modules','.git','__pycache__','.next','dist','build','venv','.venv','art','static','reports')]
            for f in files:
                ext = os.path.splitext(f)[1].lstrip('.') or 'no_ext'
                p["file_counts"][ext] = p["file_counts"].get(ext, 0) + 1
                p["total_files"] += 1

        if os.path.exists(os.path.join(path, "nuxt.config.ts")):
            p["framework"] = "Nuxt 3"

        proj_md = os.path.join(path, "PROJECT.md")
        if os.path.exists(proj_md):
            content = open(proj_md).read().lower()
            if "validation" in content: p["status"] = "validation"
            elif "building" in content: p["status"] = "building"
            elif "live" in content: p["status"] = "live"
            urls = re.findall(r'https?://[^\s\)]+', content)
            if urls: p["url"] = urls[0]

        projects.append(p)
    return projects


def get_tweet_metrics(tweet_id):
    """Fetch metrics for a specific tweet."""
    out = run_cmd(["xurl", "read", str(tweet_id)])
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

        # API routes
        if path == "/api/projects":
            self.send_json({"projects": scan_projects()})
            return

        if path == "/api/data":
            self.send_json(load_data())
            return

        if path == "/api/project/detail":
            name = query.get("name", [""])[0]
            data = load_data()
            # Get display name and goal from project metadata
            proj_meta = data.get("projects", {}).get(name, {})
            display_name = proj_meta.get("display_name", name)
            goal = proj_meta.get("goal", 50)
            
            proj = next((p for p in scan_projects() if p["name"] == name), None)
            if not proj:
                self.send_json({"error": "Not found"}, 404)
                return

            posts = [p for p in data.get("social_posts", []) if p.get("project") == name]
            for post in posts:
                if post.get("tweet_id"):
                    metrics = get_tweet_metrics(post["tweet_id"])
                    if metrics:
                        post["metrics"] = metrics

            detail = {
                **proj,
                "display_name": display_name,
                "expenses": [e for e in data.get("expenses", []) if e.get("project") == name],
                "total_spend": sum(e.get("cost", 0) for e in data.get("expenses", []) if e.get("project") == name),
                "social_posts": posts,
                "waitlist_count": data.get("waitlist_count", 0),
                "goal": goal,
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

        # Static files
        if path == "/" or path == "":
            path = "/index.html"

        file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), path.lstrip("/"))
        if os.path.isfile(file_path):
            self.send_file(file_path)
        else:
            self.send_json({"error": f"Not found: {path}"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        cl = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(cl).decode() if cl > 0 else ""

        if path == "/api/social/add":
            try:
                data = json.loads(body)
                all_data = load_data()
                post = {"id": int(time.time()*1000), "platform": data.get("platform","X"),
                        "handle": data.get("handle","@tkayosf"), "text": data.get("text",""),
                        "scheduled_date": data.get("scheduled_date",""),
                        "scheduled_time": data.get("scheduled_time","09:00"),
                        "image": data.get("image",False), "posted": data.get("posted",False),
                        "project": data.get("project",""), "tweet_id": data.get("tweet_id")}
                all_data["social_posts"].append(post)
                save_data(all_data)
                self.send_json({"success": True, "id": post["id"]})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/social/mark_posted":
            try:
                req = json.loads(body)
                all_data = load_data()
                for p in all_data["social_posts"]:
                    if p["id"] == req.get("id"):
                        p["posted"] = True
                        if req.get("tweet_id"):
                            p["tweet_id"] = req["tweet_id"]
                        break
                save_data(all_data)
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/waitlist/update":
            try:
                req = json.loads(body)
                all_data = load_data()
                all_data["waitlist_count"] = req.get("count", 0)
                save_data(all_data)
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/expense/add":
            try:
                req = json.loads(body)
                all_data = load_data()
                exp = {"id": int(time.time()*1000),
                       "date": req.get("date", time.strftime("%Y-%m-%d")),
                       "item": req.get("item",""), "category": req.get("category","Other"),
                       "cost": float(req.get("cost",0)), "project": req.get("project","")}
                all_data["expenses"].append(exp)
                save_data(all_data)
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        self.send_json({"error": "Not found"}, 404)

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
