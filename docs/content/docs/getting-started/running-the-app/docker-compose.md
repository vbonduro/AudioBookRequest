---
title: 'Docker Compose'
date: 2025-06-09T13:03:35+02:00
description: >
  How to get started using Docker-Compose.
categories: [Setup]
tags: [docker]
weight: 2
---

Docker-compose works the similar way as [Docker](./docker.md).

The basic docker compose file is as follows:

```yaml
services:
  web:
    image: markbeep/audiobookrequest:1
    ports:
      - '8000:8000'
    volumes:
      - ./config:/config
```

If you want to add any environment variables, you can add them as explained
[here](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).
It would look along the lines of this:

```yaml
services:
  web:
    image: markbeep/audiobookrequest:1
    ports:
      - '8000:5432'
    volumes:
      - ./config:/config
    environment:
      ABR_APP__PORT: 5432
      ABR_APP__OPENAPI_ENABLED: true
```
