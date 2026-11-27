FROM python:3.12-slim

WORKDIR /app

# Claude Code and Gemini CLI are deliberately NOT installed here -- this app
# runs on local Ollama/Qwen runtimes instead, so no cloud coding-agent CLI
# (and no one's personal Anthropic/Google account) is ever touched by a
# deployment of this backend. git is still needed for repository operations.
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
