# AudioBookRequest

> [!CAUTION]
> This project is in it's very early stages. It's basically a weekend project at this state. There might be some bugs or unfinished parts.

Your tool for handling audiobook requests on a Plex/AudioBookShelf/Jellyfin instance.

If you've heard of Overseer, Ombi, or Jellyseer; this is in the similar vein, <ins>but for audiobooks</ins>.

![Search Page](/media/search_page.png)

# Workflow

1. Admin creates user accounts for their friends. Each account's group is one of: `Admin`, `Trusted`, and `Untrusted`. All groups can request/remove book requests. Trusted and above can have downloads automatically start when they select a book in the search tab. This requires the download client to be set up correctly in Prowlarr.
2. The requests/wishlist page shows a list of all books that have been requested. An admin can directly view the torrent sources gotten from Prowlarr and start any download.
3. Settings page allows for admins to create new accounts and set the required Prowlarr configs.

# Docker

Using Docker, this website can be run with minimal setup:

```dockerfile
services:
  web:
    build: markbeep/audiobookrequest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/app/data
```

Inward port is `:8000` and the database (used for config and caching) is located at `/app/data`.

# Local Development

Pull requests are always welcome. Do note though, that because this project is in its very early stages a lot might change.

AudioBookRequest depends on [Prowlarr](https://wiki.servarr.com/prowlarr). Prowlarr handles the part of managing all indexers and download clients. AudioBookRequest is solely responsible for creating wishlists/request pages and starting downloads automatically if possible.

## Installation

```sh
python -m venv .venv
.venv/activate
pip install -r requirements.txt
```

## Initialize DB

```sh
alembic upgrade heads
```

## Running

Running the application is best done in multiple terminals:

1. Start FastAPI dev mode:

```sh
fastapi dev
```

2. Install daisyUI and start Tailwindcss watcher:

```sh
npm i
tailwindcss -i styles/globals.css -o static/globals.css --watch --m
```

3. Start browser-sync. This hot reloads the website when the html template files are modified:

```sh
browser-sync http://localhost:8000 --files templates/**
```

**NOTE**: Website has to be visited at http://localhost:3000 instead.
