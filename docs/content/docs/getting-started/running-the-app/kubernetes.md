---
title: 'Kubernetes'
date: 2025-06-09T13:03:35+02:00
description: >
  How to get started using Kubernetes.
categories: [Setup]
tags: [docker]
weight: 3
---

Here's an example for a kubernetes deployment file you'd use:

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
          ports:
            - name: http-request
              containerPort: 8000
      volumes:
        - name: abr-config
          hostPath:
            path: /mnt/disk/AudioBookRequest/
```

For the volume you can assign it a host path on a node, or assign it to a PVC.
