FROM python:3.12-slim
WORKDIR /app
COPY src/ni_offline /app/ni_offline
COPY docker/plant/plant.py /app/plant.py
COPY docker/plant/web /app/web
ENV PYTHONUNBUFFERED=1
EXPOSE 8080/tcp 47000/udp
CMD ["python", "/app/plant.py"]
