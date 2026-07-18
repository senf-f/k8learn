FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

EXPOSE 8000

# Run as a non-root user. Pin a numeric UID: K8s runAsNonRoot can only verify
# a non-root image user when it's numeric (it can't read the image's passwd).
RUN useradd --create-home --uid 10001 appuser
USER 10001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
