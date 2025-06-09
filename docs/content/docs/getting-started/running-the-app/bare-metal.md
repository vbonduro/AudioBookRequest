---
title: 'Bare Metal'
date: 2025-06-09T13:03:35+02:00
description: >
  How to get started **without** Docker.
categories: [Setup]
tags: [development]
weight: 10
---

{{< alert color="warning" title="Warning" >}} The bare metal approach should
only be the last option. Try to get it working with Docker or get support on the
Discord server before trying to set ABR up for a bare metal deployment.

There are no guarantees that if one version works locally that it won't suddenly
break in the next because of a new dependency, new file structure or something
else. {{< /alert >}}

To run ABR locally without Docker, the same steps as for the
[local development](../../local-development) have to be followed. First, follow
the instructions to get local development working.

Once local development works, there are a few adjustments that have to be made
to run the app in production mode instead of debug/local mode.

1. Delete the `.env.local` file or delete all contents in it.
2. Run the python script to fetch and download all required javascript files:
   `uv run python /app/util/fetch_js.py`. This should populate your `static/`
   directory with some new js files.
3. Instead of running `fastapi dev` you want to execute `fastapi start` to start
   the webserver.
4. Create a file called `.env` and place any environment variables you want to
   set in there.
5. If you intend to change the port (documented as the env variable
   `ABR_APP__PORT`), you'll have to run fastapi with the `--port <PORT>` flag:
   ```bash
   fastapi run --port 5432
   ```

With these changes your deployment will be running in production mode.
