FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server ./server
COPY web ./web
COPY manage.py .
RUN mkdir /app/data && chown -R 1000:1000 /app
USER 1000:1000
EXPOSE 8000
CMD ["python", "manage.py", "run", "--host", "0.0.0.0"]
