# Install daisyui
FROM node:23-alpine3.20

WORKDIR /app

COPY package.json package.json
COPY package-lock.json package-lock.json
RUN npm install

# Setup python
FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache curl gcompat build-base
RUN curl https://github.com/tailwindlabs/tailwindcss/releases/download/v4.0.6/tailwindcss-linux-x64-musl -L -o /bin/tailwindcss
RUN chmod +x /bin/tailwindcss

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt


COPY --from=0 /app/node_modules/ node_modules/

COPY alembic/ alembic/
COPY alembic.ini alembic.ini
COPY styles/ styles/
COPY templates/ templates/
COPY app/ app/

RUN mkdir static
RUN /bin/tailwindcss -i styles/globals.css -o static/globals.css -m

CMD alembic upgrade heads && fastapi run

EXPOSE 8000
