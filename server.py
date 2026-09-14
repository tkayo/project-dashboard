#!/usr/bin/env python3
"""Project Dashboard — tracks micro-startup portfolio."""

import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

PORT = 8766
PROJECTS_DIR = os.environ.get("PROJECTS_DIR", "/Users/tko/Development")
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")


def load_data():
    """Load persistent data (social calendar, expenses)."""
    default = {"social_posts": [], "expenses": [], "projects": {}}
    if not os.path.exists(DATA_FILE):
        return default
    try:
        with open(DATA_FILE) as f:
            data = json.load(f)
        for key in default:
            if key not in data:
                data[key] = default[key]
        return data
    except:
        return default


def save_data(data):
    """Persist data to disk."""
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def run_cmd(cmd, cwd=None, timeout=5):
    """Run a shell command, return stdout."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except:
        pass
    return None


def scan_projects():
    """Walk PROJECTS_DIR and collect metadata for each project."""
    projects = []
    if not os.path.exists(PROJECTS_DIR):
        return projects

    for name in sorted(os.listdir(PROJECTS_DIR)):
        path = os.path.join(PROJECTS_DIR, name)
        if not os.path.isdir(path) or name.startswith('.') or name.startswith('__'):
            continue

        # Skip non-project dirs
        if name.startswith('hermes') or name.startswith('.'):
            continue

        project = {
            "name": name,
            "path": path,
            "git_branch": None,
            "git_last_commit": None,
            "git_last_commit_msg": None,
            "git_last_commit_date": None,
            "file_counts": {},
            "total_files": 0,
            "has_package_json": False,
            "has_supabase": False,
            "has_stripe": False,
            "framework": "unknown",
            "status": "unknown",
            "url": None,
        }

        # Git info
        branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
        if branch:
            project["git_branch"] = branch

        last_commit = run_cmd(["git", "log", "-1", "--format=%H|%s|%ci"], cwd=path)
        if last_commit:
            parts = last_commit.split("|", 2)
            if len(parts) == 3:
                project["git_last_commit"] = parts[0]
                project["git_last_commit_msg"] = parts[1]
                project["git_last_commit_date"] = parts[2]

        # File counts + framework detection
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in ('node_modules', '.git', '__pycache__', '.next', 'dist', 'build', 'venv', '.venv', 'art', 'static', 'reports', 'workflows', 'agents', 'architecture', 'references')]
            for f in files:
                ext = os.path.splitext(f)[1].lstrip('.') or 'no_ext'
                project["file_counts"][ext] = project["file_counts"].get(ext, 0) + 1
                project["total_files"] += 1

                lf = f.lower()
                if lf == 'package.json':
                    project["has_package_json"] = True
                if 'supabase' in root.lower() or 'supabase' in lf:
                    project["has_supabase"] = True
                if 'stripe' in lf:
                    project["has_stripe"] = True

        # Detect framework
        if project["has_package_json"]:
            if os.path.exists(os.path.join(path, "nuxt.config.ts")) or os.path.exists(os.path.join(path, "nuxt.config.js")):
                project["framework"] = "Nuxt 3"
            elif os.path.exists(os.path.join(path, "next.config.js")) or os.path.exists(os.path.join(path, "next.config.ts")):
                project["framework"] = "Next.js"
            elif os.path.exists(os.path.join(path, "vite.config.ts")) or os.path.exists(os.path.join(path, "vite.config.js")):
                project["framework"] = "Vite"
            elif os.path.exists(os.path.join(path, "package.json")):
                try:
                    pkg = json.load(open(os.path.join(path, "package.json")))
                    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                    if "nuxt" in deps:
                        project["framework"] = "Nuxt 3"
                    elif "next" in deps:
                        project["framework"] = "Next.js"
                    elif "react" in deps:
                        project["framework"] = "React"
                    elif "vue" in deps:
                        project["framework"] = "Vue"
                    elif "svelte" in deps:
                        project["framework"] = "Svelte"
                    elif "express" in deps:
                        project["framework"] = "Express"
                except:
                    pass

        # Detect status from PROJECT.md or directory name hints
        if os.path.exists(os.path.join(path, "PROJECT.md")):
            try:
                content = open(os.path.join(path, "PROJECT.md")).read()
                if "validation" in content.lower():
                    project["status"] = "validation"
                elif "build" in content.lower():
                    project["status"] = "building"
                elif "live" in content.lower():
                    project["status"] = "live"
                elif "kill" in content.lower():
                    project["status"] = "killed"
            except:
                pass

        # Extract URL from PROJECT.md
        if os.path.exists(os.path.join(path, "PROJECT.md")):
            try:
                content = open(os.path.join(path, "PROJECT.md")).read()
                urls = re.findall(r'https?://[^\s\)]+', content)
                if urls:
                    project["url"] = urls[0]
            except:
                pass

        projects.append(project)

    return projects


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/projects":
            projects = scan_projects()
            self.send_json({"projects": projects})
            return

        if path == "/api/data":
            data = load_data()
            self.send_json(data)
            return

        if path == "/api/expenses":
            data = load_data()
            self.send_json({"expenses": data.get("expenses", [])})
            return

        if path == "/api/social":
            data = load_data()
            self.send_json({"posts": data.get("social_posts", [])})
            return

        if path == "/":
            path = "/index.html"

        file_path = os.path.join(os.path.dirname(__file__), path.lstrip("/"))
        if os.path.exists(file_path) and os.path.isfile(file_path):
            self.send_file(file_path)
        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode() if content_length > 0 else ""

        if path == "/api/social/add":
            try:
                data = json.loads(body)
                all_data = load_data()
                post = {
                    "id": int(time.time() * 1000),
                    "platform": data.get("platform", "X"),
                    "handle": data.get("handle", "@tkayosf"),
                    "text": data.get("text", ""),
                    "scheduled_date": data.get("scheduled_date", ""),
                    "scheduled_time": data.get("scheduled_time", "09:00"),
                    "image": data.get("image", False),
                    "posted": data.get("posted", False),
                    "project": data.get("project", ""),
                }
                all_data["social_posts"].append(post)
                save_data(all_data)
                self.send_json({"success": True, "id": post["id"]})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/social/mark_posted":
            try:
                data = json.loads(body)
                post_id = data.get("id")
                all_data = load_data()
                for p in all_data["social_posts"]:
                    if p["id"] == post_id:
                        p["posted"] = True
                        break
                save_data(all_data)
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/expense/add":
            try:
                data = json.loads(body)
                all_data = load_data()
                expense = {
                    "id": int(time.time() * 1000),
                    "date": data.get("date", datetime.now().strftime("%Y-%m-%d")),
                    "item": data.get("item", ""),
                    "category": data.get("category", "Other"),
                    "cost": float(data.get("cost", 0)),
                    "project": data.get("project", ""),
                }
                all_data["expenses"].append(expense)
                save_data(all_data)
                self.send_json({"success": True, "id": expense["id"]})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        if path == "/api/project/update":
            try:
                data = json.loads(body)
                project_name = data.get("name", "")
                all_data = load_data()
                if project_name not in all_data["projects"]:
                    all_data["projects"][project_name] = {}
                all_data["projects"][project_name].update(data.get("updates", {}))
                save_data(all_data)
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)}, 500)
            return

        self.send_json({"error": "Not found"}, 404)

    def send_json(self, data, status=200):
        response = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(response)

    def send_file(self, path):
        try:
            with open(path, "rb") as f:
                content = f.read()
            content_type = "application/octet-stream"
            if path.endswith(".html"):
                content_type = "text/html"
            elif path.endswith(".js"):
                content_type = "application/javascript"
            elif path.endswith(".css"):
                content_type = "text/css"
            elif path.endswith(".json"):
                content_type = "application/json"
            elif path.endswith(".svg"):
                content_type = "image/svg+xml"
            elif path.endswith(".png"):
                content_type = "image/png"
            elif path.endswith(".ico"):
                content_type = "image/x-icon"

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


def main():
    server = HTTPServer(("127.0.0.1", PORT), DashboardHandler)
    print(f"Project Dashboard running on http://127.0.0.1:{PORT}")
    print(f"Projects dir: {PROJECTS_DIR}")
    print(f"Data file: {DATA_FILE}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
