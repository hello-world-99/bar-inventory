FROM postgres:16-alpine
RUN apk add --no-cache tzdata
COPY pgtool.sh /usr/local/bin/pgtool
RUN sed -i 's/\r$//' /usr/local/bin/pgtool && chmod 0755 /usr/local/bin/pgtool
VOLUME /backups
ENTRYPOINT []
CMD ["pgtool", "daemon"]
