FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

ENV PYTHONUNBUFFERED=1
ENV COMMU_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
RUN python -m pip install --no-cache-dir .
RUN mkdir -p /data && chown -R pwuser:pwuser /data /app
USER pwuser
VOLUME ["/data"]
CMD ["commu"]
