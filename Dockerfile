FROM python:3.11-slim

# tesseract-ocr binary is required by the Tesseract adapter (default-on engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

ARG ENGINES=""
RUN pip install --no-cache-dir --upgrade pip \
    && if [ -n "$ENGINES" ]; then \
         pip install --no-cache-dir ".[$ENGINES]"; \
       else \
         pip install --no-cache-dir .; \
       fi

EXPOSE 8000
CMD ["python", "-m", "ocrhub.main"]
