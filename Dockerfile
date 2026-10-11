FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY data ./data
COPY web ./web
ENV PYTHONPATH=src PORT=8000
EXPOSE 8000
CMD ["python", "-m", "brightwood_support.server"]
