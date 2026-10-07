FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV HOST=0.0.0.0 PORT=8000 STORY_DATA_DIR=/data HOSTED=1
VOLUME /data
EXPOSE 8000
CMD ["python", "run.py"]
