FROM python:3.12-slim AS runtime
# Fixed uid/gid so a bind-mounted state dir can be made writable deterministically:
#   chown -R 10001:10001 ./guardian-state
RUN groupadd -r -g 10001 guardian && useradd -r -u 10001 -g guardian guardian \
    && mkdir -p /state && chown guardian:guardian /state
WORKDIR /app
COPY guardian ./guardian
RUN chown -R guardian:guardian /app
USER guardian
ENV PYTHONUNBUFFERED=1
VOLUME /state
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-m", "guardian.healthcheck", "/config/guardian.yaml"]
ENTRYPOINT ["python", "-m", "guardian"]
CMD ["--config", "/config/guardian.yaml"]
