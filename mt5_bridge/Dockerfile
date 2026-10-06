FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py ftmo_guard.py ./
COPY mt5_bridge ./mt5_bridge
ENV DATA_DIR=/tmp/bridge-import
CMD ["python", "-m", "mt5_bridge.server"]
