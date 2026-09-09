import base64
import json
import logging
import os
import sqlite3
import threading
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from flask import Flask, Response, g, jsonify, request, render_template

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hubdash.favicon")

DB_PATH = Path(__file__).parent / "data" / "links.db"

FAVICON_UA = "HubDash/1.0"
FAVICON_TIMEOUT = 5

TRANSPARENT_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

app = Flask(__name__)


@app.after_request
def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


SEED_LINKS = [
    ("GitHub", "https://github.com", None, "development", 0),
    ("Stack Overflow", "https://stackoverflow.com", None, "development", 1),
    ("MDN Web Docs", "https://developer.mozilla.org", None, "development", 2),
    ("Docker Hub", "https://hub.docker.com", None, "devops", 0),
    ("YouTube", "https://youtube.com", None, "media", 0),
    ("Reddit", "https://reddit.com", None, "social", 0),
    ("Wikipedia", "https://wikipedia.org", None, "reference", 0),
    ("Hacker News", "https://news.ycombinator.com", None, "news", 0),
]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            icon TEXT,
            category TEXT DEFAULT 'general',
            sort_order INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cols = {row[1] for row in db.execute("PRAGMA table_info(links)")}
    if "favicon" not in cols:
        db.execute("ALTER TABLE links ADD COLUMN favicon BLOB")
    if "favicon_type" not in cols:
        db.execute("ALTER TABLE links ADD COLUMN favicon_type TEXT DEFAULT 'image/x-icon'")
    count = db.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    if count == 0:
        db.executemany(
            "INSERT INTO links (name, url, icon, category, sort_order) VALUES (?, ?, ?, ?, ?)",
            SEED_LINKS,
        )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY,
            query TEXT NOT NULL,
            results TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    db.commit()
    db.close()


class IconLinkParser(HTMLParser):
    icon_href = None

    def handle_starttag(self, tag, attrs):
        if tag != "link" or self.icon_href:
            return
        attrs = dict(attrs)
        rel = (attrs.get("rel") or "").lower()
        if rel in ("icon", "shortcut icon") and attrs.get("href"):
            self.icon_href = attrs["href"]


def fetch_favicon(url):
    headers = {"User-Agent": FAVICON_UA}
    try:
        page = requests.get(url, headers=headers, timeout=FAVICON_TIMEOUT, allow_redirects=True)
        parser = IconLinkParser()
        parser.feed(page.text)
        if parser.icon_href:
            icon_url = urljoin(page.url, parser.icon_href)
            resp = requests.get(icon_url, headers=headers, timeout=FAVICON_TIMEOUT, allow_redirects=True)
            if resp.ok and resp.content:
                return resp.content, resp.headers.get("Content-Type", "image/x-icon")
    except requests.RequestException as e:
        logger.warning("favicon <link> fetch failed for %s: %s", url, e)
    except Exception as e:
        logger.warning("favicon parse failed for %s: %s", url, e)

    try:
        parsed = urlparse(url)
        root_favicon = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        resp = requests.get(root_favicon, headers=headers, timeout=FAVICON_TIMEOUT, allow_redirects=True)
        if resp.ok and resp.content:
            return resp.content, resp.headers.get("Content-Type", "image/x-icon")
    except requests.RequestException as e:
        logger.warning("favicon.ico fetch failed for %s: %s", url, e)

    logger.warning("no favicon found for %s, using transparent placeholder", url)
    return None, None


class DuckDuckGoResultParser(HTMLParser):
    """Pulls {title, url, snippet} out of html.duckduckgo.com/html/ markup."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._in_link = False
        self._in_snippet = False
        self._cur = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._in_link = True
            self._cur = {"title": "", "url": attrs.get("href", ""), "snippet": ""}
        elif tag == "a" and "result__snippet" in classes:
            self._in_snippet = True
            if self._cur is None:
                self._cur = {"title": "", "url": "", "snippet": ""}

    def handle_data(self, data):
        if self._in_link and self._cur is not None:
            self._cur["title"] += data
        elif self._in_snippet and self._cur is not None:
            self._cur["snippet"] += data

    def handle_endtag(self, tag):
        if tag == "a":
            if self._in_link:
                self._in_link = False
            elif self._in_snippet:
                self._in_snippet = False
                if self._cur is not None:
                    self._cur["title"] = self._cur["title"].strip()
                    self._cur["snippet"] = self._cur["snippet"].strip()
                    self._cur["url"] = unwrap_ddg_url(self._cur["url"])
                    if self._cur["url"]:
                        self.results.append(self._cur)
                    self._cur = None


def unwrap_ddg_url(href):
    """DDG html-lite wraps result links in /l/?uddg=<real url>&rut=..."""
    parsed = urlparse(href if "//" in href.split("?")[0] else "https:" + href)
    if parsed.path == "/l/" and "uddg" in parse_qs(parsed.query):
        return parse_qs(parsed.query)["uddg"][0]
    return href


def row_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "url": row["url"],
        "icon": row["icon"],
        "category": row["category"],
        "sort_order": row["sort_order"],
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/links", methods=["GET"])
def get_links():
    db = get_db()
    rows = db.execute("SELECT * FROM links ORDER BY category, sort_order").fetchall()
    return jsonify([row_to_dict(r) for r in rows])


@app.route("/api/links", methods=["POST"])
def add_link():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    if not name or not url:
        return jsonify({"error": "name and url are required"}), 400
    icon = data.get("icon")
    category = data.get("category") or "general"
    sort_order = data.get("sort_order", 0)
    db = get_db()
    cur = db.execute(
        "INSERT INTO links (name, url, icon, category, sort_order) VALUES (?, ?, ?, ?, ?)",
        (name, url, icon, category, sort_order),
    )
    db.commit()
    row = db.execute("SELECT * FROM links WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify(row_to_dict(row)), 201


@app.route("/api/links/reorder", methods=["PUT"])
def reorder_links():
    data = request.get_json(force=True) or []
    db = get_db()
    for item in data:
        db.execute(
            "UPDATE links SET sort_order = ? WHERE id = ?",
            (item["sort_order"], item["id"]),
        )
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/links/<int:link_id>", methods=["PUT"])
def update_link(link_id):
    data = request.get_json(force=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404
    name = data.get("name", row["name"])
    url = data.get("url", row["url"])
    icon = data.get("icon", row["icon"])
    category = data.get("category", row["category"])
    sort_order = data.get("sort_order", row["sort_order"])
    db.execute(
        "UPDATE links SET name=?, url=?, icon=?, category=?, sort_order=? WHERE id=?",
        (name, url, icon, category, sort_order, link_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    return jsonify(row_to_dict(row))


@app.route("/api/links/<int:link_id>", methods=["DELETE"])
def delete_link(link_id):
    db = get_db()
    db.execute("DELETE FROM links WHERE id = ?", (link_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/categories", methods=["GET"])
def get_categories():
    db = get_db()
    rows = db.execute(
        "SELECT DISTINCT category FROM links ORDER BY category"
    ).fetchall()
    return jsonify([r["category"] for r in rows])


@app.route("/api/search", methods=["GET"])
def search():
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"error": "q is required"}), 400

    resp = requests.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10,
    )
    parser = DuckDuckGoResultParser()
    parser.feed(resp.text)
    results = parser.results

    db = get_db()
    db.execute(
        "INSERT INTO searches (query, results) VALUES (?, ?)",
        (query, json.dumps(results)),
    )
    db.commit()
    return jsonify(results)


@app.route("/api/search/history", methods=["GET"])
def search_history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM searches ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    return jsonify([
        {
            "id": r["id"],
            "query": r["query"],
            "results": json.loads(r["results"]) if r["results"] else [],
            "created_at": r["created_at"],
        }
        for r in rows
    ])


@app.route("/api/search/<int:search_id>", methods=["DELETE"])
def delete_search(search_id):
    db = get_db()
    db.execute("DELETE FROM searches WHERE id = ?", (search_id,))
    db.commit()
    return jsonify({"ok": True})


@app.route("/api/favicon/<int:link_id>", methods=["GET"])
def get_favicon(link_id):
    db = get_db()
    row = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404

    if row["favicon"]:
        return Response(row["favicon"], mimetype=row["favicon_type"] or "image/x-icon")

    try:
        content, content_type = fetch_favicon(row["url"])
    except Exception as e:
        logger.exception("unexpected error fetching favicon for link %s (%s): %s", link_id, row["url"], e)
        content, content_type = None, None

    if content:
        db.execute(
            "UPDATE links SET favicon = ?, favicon_type = ? WHERE id = ?",
            (content, content_type, link_id),
        )
        db.commit()
        return Response(content, mimetype=content_type)

    return Response(TRANSPARENT_PNG, mimetype="image/png")


@app.route("/api/favicon/refresh/<int:link_id>", methods=["POST"])
def refresh_favicon(link_id):
    db = get_db()
    row = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        return jsonify({"error": "not found"}), 404

    db.execute("UPDATE links SET favicon = NULL WHERE id = ?", (link_id,))
    db.commit()

    content, content_type = fetch_favicon(row["url"])
    if content:
        db.execute(
            "UPDATE links SET favicon = ?, favicon_type = ? WHERE id = ?",
            (content, content_type, link_id),
        )
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/favicon/refresh-all", methods=["POST"])
def refresh_all_favicons():
    db = get_db()
    db.execute("UPDATE links SET favicon = NULL")
    db.commit()
    return jsonify({"ok": True})


def prefetch_all_favicons():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute("SELECT id, url FROM links WHERE favicon IS NULL").fetchall()
        for row in rows:
            try:
                content, content_type = fetch_favicon(row["url"])
            except Exception as e:
                logger.exception("prefetch failed for link %s (%s): %s", row["id"], row["url"], e)
                continue
            if content:
                db.execute(
                    "UPDATE links SET favicon = ?, favicon_type = ? WHERE id = ?",
                    (content, content_type, row["id"]),
                )
                db.commit()
    finally:
        db.close()


init_db()
threading.Thread(target=prefetch_all_favicons, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 7070)))
