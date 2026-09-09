# HUB.DASH

*A retro-styled self-hosted dashboard for your homelab links.*

**[Live Demo](https://abduznik.github.io/hub-dashboard/)**

[![License](https://img.shields.io/github/license/abduznik/hub-dashboard)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/abduznik/hub-dashboard)](https://github.com/abduznik/hub-dashboard/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/abduznik/hub-dashboard)](https://github.com/abduznik/hub-dashboard/network/members)
[![Last commit](https://img.shields.io/github/last-commit/abduznik/hub-dashboard)](https://github.com/abduznik/hub-dashboard/commits)
[![GitHub issues](https://img.shields.io/github/issues/abduznik/hub-dashboard)](https://github.com/abduznik/hub-dashboard/issues)
[![Sponsor](https://img.shields.io/badge/Sponsor-abduznik-ea4aaa)](https://github.com/sponsors/abduznik)

HUB.DASH is a single-file Flask app with a SQLite backend that gives you a link launcher for all your self-hosted services and favorite sites — styled like an early-2000s Windows XP forum. It fetches and caches favicons locally (no third-party favicon services), and includes a built-in DuckDuckGo search box with history.

## Screenshots

*(Add your own screenshots here — e.g. `docs/screenshot-home.png`, `docs/screenshot-search.png`)*

## Features

- Retro XP-era forum styling — bevels, boot screen, taskbar-style nav
- Local favicon proxy — fetches and caches favicons server-side, no external favicon API
- DuckDuckGo search with persistent history
- Category filtering via tabs
- Drag-to-reorder links
- Edit mode for adding/removing/reordering links inline
- Responsive layout
- Single-file backend, SQLite storage, no build step

## Quick Start (Docker)

```bash
git clone https://github.com/abduznik/hub-dashboard.git
cd hub-dashboard
docker compose up -d
```

The app will be available at `http://localhost:7070`.

Your links and search history persist in `./data/links.db`.

## Manual Setup

```bash
pip install -r requirements.txt
python app.py
```

Requires Python 3.9+.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT`   | `7070`  | Port the app listens on |

## Default Demo Links

On first run, HUB.DASH seeds itself with a handful of well-known public sites (GitHub, Stack Overflow, MDN, Docker Hub, YouTube, Reddit, Wikipedia, Hacker News) across a few categories, just so the dashboard isn't empty. Delete or edit them via edit mode — they're only there to demonstrate categories and layout.

## License

MIT — see [LICENSE](LICENSE).
