![Header](/media/AudioBookRequestIcon.png)

Your tool for handling audiobook requests on a Plex/Audiobookshelf/Jellyfin instance.

If you've heard of Overseer, Ombi, or Jellyseer; this is in the similar vein, <ins>but for audiobooks</ins>.

![Search Page](/media/search_page.png)

## Table of Contents

- [Getting Started](#getting-started)
  - [Quick Start](#quick-start)
  - [Usage](#usage)
    - [Auto download](#auto-download)
    - [Notifications](#notifications)
  - [Alternative Deployments](#alternative-deployments)
    - [Environment Variables](#environment-variables)
- [Contributing](#contributing)
  - [Local Development](#local-development)
  - [Initialize Database](#initialize-database)
  - [Running](#running)

# Getting Started

AudioBookRequest is intended to be deployed using Docker or Kubernetes. For "bare-metal" deployments, head to the [local development](#Contributing) section.

## Quick Start

Run the image directly:

```bash
docker run -p 8000:8000 -v $(pwd)/config:/config markbeep/audiobookrequest:1
```

Then head to http://localhost:8000.

## Usage

1. Logging in the first time the login-type and root admin user has to be configured.
2. Head to `Settings>Users` to create accounts for your friends.
3. Any user can search for books and request them by clicking the `+` button.
4. The admin can head to the wishlist to see all the books that have been requested.

### Auto download

Auto-downloading enables requests by `Trusted` and `Admin` users to directly start downloading once requested.

1. Ensure your Prowlarr instance is correctly set up with any indexers and download clients you want. [More info](https://prowlarr.com/).
2. On Prowlarr, head to `Settings>General` and copy the `API Key`.
3. On AudioBookRequest, head to `Settings>Prowlarr` and enter the API key as well as the base URL of your Prowlarr instance, i.e. `https://prowlarr.example.com`.
4. Head to `Settings>Download` to configure the automatic download settings:
   1. Enable `Auto Download` at the top.
   2. The remaining heuristics determine the ranking of any sources retrieved from Prowlarr.
   3. Indexer flags allow you to add priorities to certain sources like freeleeches.

### Notifications

Notifications depend on [Apprise](https://github.com/caronc/apprise).

1. Ensure you have a working Apprise instance.
2. On Apprise, create a new configuration. For example paste your Discord webhook link (`https://discord.com/api/webhooks/<channel>/<id>`) into the configuration.
3. On Apprise, copy the notification url along the format of `https://apprise.example.com/notify/<id>`.
4. On AudioBookRequest, head to `Settings>Notifications` and add the URL.
5. Configure the remaining settings. **The event variables are case sensitive**.

## Alternative Deployments

Docker image is located on [dockerhub](https://hub.docker.com/r/markbeep/audiobookrequest).

**NOTE:** It is not recommended to use `:latest` in case of incompatible changes that are not backwards compatible. For versioning, [SemVer](https://semver.org/) is used.

For experimental builds (latest commits to `main`), the `:nightly` version can be used.

**Docker compose**

```yaml
services:
  web:
    image: markbeep/audiobookrequest:1
    ports:
      - "8000:8765"
    environment:
      ABR_APP__PORT: 8765
    volumes:
      - ./config:/config
```

**Kubernetes**

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: audiobookrequest
  labels:
    app: audiobookrequest
spec:
  replicas: 1
  selector:
    matchLabels:
      app: audiobookrequest
  template:
    metadata:
      labels:
        app: audiobookrequest
    spec:
      containers:
        - name: audiobookrequest
          image: markbeep/audiobookrequest:1
          imagePullPolicy: Always
          volumeMounts:
            - mountPath: /config
              name: abr-config
          env:
            - name: ABR_APP__PORT
              value: "8765"
          ports:
            - name: http-request
              containerPort: 8765
      volumes:
        - name: abr-config
          hostPath:
            path: /mnt/disk/AudioBookRequest/
```

### Environment Variables

| ENV                        | Description                                                                                                                                                                               | Default   |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| `ABR_APP__PORT`            | The port to run the server on.                                                                                                                                                            | 8000      |
| `ABR_APP__DEBUG`           | If to enable debug mode. Not recommended for production.                                                                                                                                  | false     |
| `ABR_APP__OPENAPI_ENABLED` | If set to `true`, enables an OpenAPI specs page on `/docs`.                                                                                                                               | false     |
| `ABR_APP__CONFIG_DIR`      | The directory path where persistant data and configuration is stored. If ran using Docker or Kubernetes, this is the location a volume should be mounted to.                              | /config   |
| `ABR_DB__SQLITE_PATH`      | If relative, path and name of the sqlite database in relation to `ABR_APP__CONFIG_DIR`. If absolute (path starts with `/`), the config dir is ignored and only the absolute path is used. | db.sqlite |

---

# Contributing

Pull requests are always welcome. Do note though that a big goal is to keep this project on a smaller scale. The main focus of this project is to make it easy for friends to request and potentially automatically download Audiobooks without having to give direct access to Readarr/Prowlarr.

## Local Development

Virtual environments help isolate any installed packages to this directory. Project was made with `Python 3.11`. Any python version above 3.9 _should_ work, but if there are any problems use `>= 3.11`.

```sh
python -m venv .venv

source .venv/bin/activate # sh/bash
source .venv/bin/activate.fish # fish
.venv\Scripts\activate.bat # cmd
.venv\Scripts\Activate.ps1 # powershell

pip install -r requirements.txt
```

For local development, environment variables can be added to `.env.local` and they'll be used wherever required.

## Initialize Database

[Alembic](https://alembic.sqlalchemy.org/en/latest/) is used to create database migrations. Run the following before starting up the application for the first time. It will initialize the directory if non-existant, create the database file as well as execute any required migrations.

```sh
alembic upgrade heads
```

_In case of any model changes, remember to create migrations using `alembic revision --autogenerate -m "<message>"`._

## Running

Running the application is best done in multiple terminals:

1. Start FastAPI dev mode:

```sh
fastapi dev
```

Website can be visited at http://localhost:8000.

2. Install daisyUI and start Tailwindcss watcher. Required for any CSS styling.

```sh
npm i
tailwindcss -i styles/globals.css -o static/globals.css --watch
# Alternatively npx can be used to run tailwindcss
npx @tailwindcss/cli@4 -i styles/globals.css -o static/globals.css --watch
```

3. _Optional:_ Start browser-sync. This hot reloads the website when the html template or python files are modified:

```sh
browser-sync http://localhost:8000 --files templates/** --files app/**
```

**NOTE**: Website has to be visited at http://localhost:3000 instead.
