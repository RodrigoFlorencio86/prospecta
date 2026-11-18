FROM python:3.12-slim
RUN useradd --create-home --uid 10002 prospecta && mkdir -p /dados && chown prospecta /dados
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY prospecta/ prospecta/
USER prospecta
ENV PYTHONUNBUFFERED=1 PASTA_DADOS=/dados
CMD ["python", "-m", "prospecta", "bot"]
