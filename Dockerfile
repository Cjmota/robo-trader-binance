# Usa Python estável
FROM python:3.12-slim

# Diretório de trabalho
WORKDIR /app

# Copia tudo do projeto
COPY . .

# Instala dependências
RUN pip install --no-cache-dir -r requirements.txt

# Comando para rodar o bot
CMD ["python", "main.py"]