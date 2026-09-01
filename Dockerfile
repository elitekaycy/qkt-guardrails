FROM python:3.12-slim AS runtime
RUN groupadd -r guardian && useradd -r -g guardian guardian
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
