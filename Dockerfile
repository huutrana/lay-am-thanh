FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py ./
COPY static ./static
RUN useradd --create-home audioapp && mkdir /app/data && chown audioapp:audioapp /app/data
USER audioapp
ENV HOST=0.0.0.0 PORT=8765 PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "app.py"]
