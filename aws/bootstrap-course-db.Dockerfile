FROM postgres:16-alpine
COPY docs/review2/sql /migrations
COPY aws/bootstrap-course-db.sh /usr/local/bin/bootstrap-course-db
RUN chmod 0555 /usr/local/bin/bootstrap-course-db
ENTRYPOINT ["/usr/local/bin/bootstrap-course-db"]
