FROM python:3.11-slim
WORKDIR /opt/ventobserve
COPY requirements-platform.txt .
RUN pip install --no-cache-dir -r requirements-platform.txt
COPY app ./app
COPY docs ./docs
EXPOSE 8765
CMD ["python", "-m", "app.server", "--host", "0.0.0.0", "--mode", "platform"]
