FROM postgres:17-alpine

RUN apk add --no-cache pgbouncer
COPY start.sh /usr/local/bin/start-pgbouncer
USER postgres
ENTRYPOINT ["sh", "/usr/local/bin/start-pgbouncer"]
