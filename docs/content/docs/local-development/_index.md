---
title: Local Development
description: How to set up the project for local development.
categories: [Development]
tags: [local]
weight: 9
---

## Requirements

- Python >3.12
- [uv](https://docs.astral.sh/uv/). Used as the package manager
- node.js. Exact version is not too important. Too old versions might fail when
  installing packages.

## Setup

Virtual environments help isolate any installed packages to this directory.
Project was made with `Python 3.12` and uses new generics introduced in 3.12.
Older python versions might not work or could have incorrect typing.

For improved dependency management, `uv` is used instead of `pip`.

```sh
# This creates the venv as well as installs all dependencies
uv sync
```

For local development, environment variables can be added to `.env.local` and
they'll be used wherever required. This file is not used in production.

## Initialize Database

[Alembic](https://alembic.sqlalchemy.org/en/latest/) is used to create database
migrations. Run the following before starting up the application for the first
time. It will initialize the directory if non-existant, create the database file
as well as execute any required migrations.

```sh
uv run alembic upgrade heads
```

_In case of any model changes, remember to create migrations using
`alembic revision --autogenerate -m "<message>"`._

## Generate the CSS files

[Tailwindcss](https://tailwindcss.com/) is used to style elements using CSS. On
top of that, [daisyUI](https://daisyui.com/) is for easy and consistent
component styling.

Install daisyUI and start Tailwindcss watcher. Required for any CSS styling.

```sh
npm i
uv run tailwindcss -i static/tw.css -o static/globals.css --watch
# Alternatively npx can be used to run tailwindcss
npx @tailwindcss/cli@4 -i static/tw.css -o static/globals.css --watch
```

Tailwind has to run anytime something is changed in the HTML template files.

## Run the app

Running the application is best done in multiple terminals:

1.  Start FastAPI dev mode:

    ```sh
    uv run fastapi dev
    ```

    Website can be visited at http://localhost:8000.

2.  _Optional:_ Start browser-sync. This hot reloads the website when the html
    template or python files are modified:

```sh
browser-sync http://localhost:8000 --files templates/** --files app/**
```

**NOTE**: Website has to be visited at http://localhost:3000 instead.

## Docker Compose

The docker compose can also be used to run the app locally. Any services that
are required can be added to it for easy testing:

```bash
docker compose up --build
```

The local context (ABR) is in a docker compose profile called `local`, which is
only run if explicitly stated as follows:

```bash
docker compose --profile local up
```
