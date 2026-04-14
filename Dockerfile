FROM python:3.11-slim

# Evita logs bufferizados (importante pro Railway)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copia só requirements primeiro (cache inteligente)
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Agora copia o resto do projeto
COPY . .

# Porta do dashboard (se usar Flask)
EXPOSE 3000

CMD ["python", "src/main.py"]