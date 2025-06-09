---
title: 'Docker'
date: 2025-06-09T13:03:35+02:00
description: >
  How to get started using Docker.
categories: [Setup]
tags: [docker]
weight: 1
---

If you prefer to run the app manually with docker, you can simply run the
following command:

```bash
docker run -p 8000:8000 -v $(pwd)/config:/config markbeep/audiobookrequest:1
```

This will start the container on port 8000 and create the `config/` directory in
your current working directory.

The above command might break on Windows. Instead, use
`${PWD}\config:/config ...` in PowerShell or `%cd%\config:/config ...` in
Windows Command Prompt.

{{% alert title="Versions" %}}The `:1` at the end denotes the image version.
Check [dockerhub](https://hub.docker.com/r/markbeep/audiobookrequest/tags) for
any other versions you can use instead.

The `:latest` tag will give you the last non-nightly release, but it is not
recommended incase of changes that are not backwards compatible.

For experimental builds (latest commits in the `main` branch of the repository),
the `:nightly` version tag can be used. {{% /alert %}}
