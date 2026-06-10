<div align="center">

<img src="logo.jpg" alt="FrogFind! NG" width="220">

# FrogFind! NG

**Makes the modern web accessible on vintage computers**

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12+-green.svg)](https://www.python.org/)
[![Fork of FrogFind!](https://img.shields.io/badge/Fork%20of-FrogFind!-orange.svg)](https://github.com/ActionRetro/FrogFind)

*A Python reimplementation of [FrogFind!](https://github.com/ActionRetro/FrogFind) by [Action Retro](https://www.youtube.com/@ActionRetro)*

</div>

---

## What is FrogFind! NG?

FrogFind! NG is a retro web proxy that strips modern websites down to plain **HTML 2.0** — making them readable on vintage computers from the 1980s and 90s such as the Commodore 64, Amiga, Apple II, early Macs, and any system running browsers like Lynx, Mosaic, or the original Internet Explorer.

This project is a **Python reimplementation** of the original [FrogFind!](https://github.com/ActionRetro/FrogFind) PHP project by Sean / Action Retro, rebuilt production-ready with FastAPI, Docker, and several new features.

---

## Features

| Feature | Description |
|---|---|
| 🔍 **Web Search** | DuckDuckGo-powered search, results rendered as plain HTML |
| 📄 **Article Reader** | Mozilla Readability algorithm strips pages to readable text |
| 🖼️ **Image Proxy** | Resizes images to max 300px, converts to JPEG/PNG for slow connections |
| 📖 **Wikipedia** | Quick encyclopedia lookup — summary + thumbnail, no JS required |
| 💬 **Reddit Reader** | Browse subreddits and posts via RSS (+ OAuth2 for comments) |
| 📰 **Google News** | Top headlines, 8 categories, keyword search via RSS |
| 🌤️ **Retro Weather** | Current conditions + 7-day forecast (Open-Meteo + Nominatim, no API key) |
| 🏛️ **Wayback Machine** | Every article links to its Internet Archive snapshot |
| 🔒 **Admin Panel** | Hidden path, JWT auth, rate limiting, IP blocklist, maintenance mode |

---

## Fork Notice

> This project is a fork of **[FrogFind!](https://github.com/ActionRetro/FrogFind)** by **Sean / Action Retro**.
> The original concept, name, and core idea belong to him.
> FrogFind! NG is a complete Python reimplementation with extended features,
> released under the same **GPL-3.0** license.
>
> 📺 Watch the original project: [youtube.com/@ActionRetro](https://www.youtube.com/@ActionRetro)

---

## Tech Stack

- **[FastAPI](https://fastapi.tiangolo.com/)** + Uvicorn/Gunicorn — async Python web framework
- **[readability-lxml](https://github.com/buriy/python-readability)** — Mozilla Readability algorithm (same as original)
- **[BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)** + lxml — HTML parsing
- **[Pillow](https://python-pillow.org/)** — image resizing and conversion
- **[Redis](https://redis.io/)** — caching + rate limit storage
- **[slowapi](https://github.com/laurentS/slowapi)** — rate limiting
- **[Nginx](https://nginx.org/)** — reverse proxy, bot protection
- **[Docker Compose](https://docs.docker.com/compose/)** — production deploy
- **[Open-Meteo](https://open-meteo.com/)** + **[Nominatim](https://nominatim.org/)** — weather (no API key)

---

## Quick Start (Local)

**Requirements:** Python 3.12+, Redis (or use `USE_FAKEREDIS=true`)

```bash
git clone https://github.com/RayTrunk/frogfind-ng.git
cd frogfind-ng

# Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
.venv\Scripts\activate           # Windows

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — at minimum set USE_FAKEREDIS=true for local dev
# Generate admin credentials:
python scripts/generate_admin.py

# Run
uvicorn app.main:app --reload --port 8000
```

Open: [http://localhost:8000](http://localhost:8000)

---

## Docker Deploy (Production)

```bash
cp .env.example .env
# Edit .env — set REDIS_PASSWORD, ADMIN_PATH, ADMIN_PASSWORD_HASH, ADMIN_SECRET_KEY

bash deploy.sh
```

The deploy script checks all prerequisites and runs `docker compose build && docker compose up -d`.

**Services:**
- `nginx` — reverse proxy on port 80 (and optionally 443)
- `app` — FastAPI application (internal port 8000)
- `redis` — cache and rate limit storage (internal only)

---

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable | Description | Default |
|---|---|---|
| `USE_FAKEREDIS` | Use in-memory Redis for local dev | `false` |
| `REDIS_PASSWORD` | Redis password | `changeme` |
| `ADMIN_PATH` | Hidden admin panel path | *(auto-generated)* |
| `ADMIN_PASSWORD_HASH` | bcrypt hash of admin password | — |
| `ADMIN_SECRET_KEY` | JWT signing key | *(auto-generated)* |
| `REDDIT_CLIENT_ID` | Reddit OAuth2 client ID (optional) | — |
| `REDDIT_CLIENT_SECRET` | Reddit OAuth2 client secret (optional) | — |
| `CACHE_TTL_SEARCH` | Search result cache TTL (seconds) | `600` |
| `CACHE_TTL_ARTICLE` | Article cache TTL (seconds) | `1800` |

### Reddit OAuth2 (optional)

Without credentials: Reddit works in RSS mode (subreddit listings + search).  
With credentials: Full post detail + comments are available.

Register a free **script** app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and set `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` in `.env`.

### Generate Admin Credentials

```bash
python scripts/generate_admin.py
# Copy the output values into your .env
```

---

## Security Features

- **SSRF protection** — blocks all RFC-1918, link-local, and loopback ranges
- **Bot UA blocking** — Nginx + middleware blocks known scrapers
- **Rate limiting** — per-endpoint limits via slowapi + Redis
- **Honeypot paths** — common scanner paths return 404
- **Hidden admin** — configurable path, brute-force protected (10 req/min)
- **Input validation** — all settings validated before storage
- **`javascript:` / `data:` blocking** — scheme filter on all proxied links
- **Security headers** — X-Frame-Options, X-Content-Type-Options, etc.

---

## Project Structure

```
frogfind-ng/
├── app/
│   ├── routes/          # FastAPI route handlers
│   │   ├── search.py    # Web search
│   │   ├── reader.py    # Article reader
│   │   ├── wiki.py      # Wikipedia lookup
│   │   ├── reddit.py    # Reddit reader
│   │   ├── news.py      # Google News
│   │   ├── weather.py   # Retro weather
│   │   ├── image.py     # Image proxy
│   │   └── admin.py     # Admin panel
│   ├── services/        # Business logic
│   ├── security/        # SSRF, middleware, auth
│   ├── templates/       # Jinja2 HTML 2.0 templates
│   └── config.py        # pydantic-settings configuration
├── nginx/               # Nginx reverse proxy config
├── scripts/             # Admin credential generator
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

---

## Credits

| Role | Person |
|---|---|
| **Original FrogFind! concept & PHP implementation** | [Sean / Action Retro](https://www.youtube.com/@ActionRetro) |
| **Python reimplementation (FrogFind! NG)** | Ray Trunk |

---

## License

This project is licensed under the **GNU General Public License v3.0** — the same license as the original [FrogFind!](https://github.com/ActionRetro/FrogFind).

See [LICENSE](https://www.gnu.org/licenses/gpl-3.0.en.html) for details.

---

<div align="center">
<i>FrogFind! NG — Search the modern web on vintage computers</i>
</div>
