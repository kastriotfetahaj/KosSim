FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser:appuser /app

COPY --chown=appuser:appuser app.py .

USER appuser

CMD ["python", "app.py"]
