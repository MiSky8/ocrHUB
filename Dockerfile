FROM python:3.11-slim

# tesseract-ocr binary is required by the Tesseract adapter (default-on engine)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./

# Install dependencies first, against a stub package, so this (slow, multi-GB)
# layer is cached and only re-runs when pyproject.toml or ENGINES change - not
# on every source edit.
ARG ENGINES=""
# Surya needs torch, and on Linux PyPI's torch drags in several GB of NVIDIA CUDA
# wheels that a CPU container never uses. Install the CPU build first; pip then
# sees torch>=2.7 as already satisfied and leaves it alone.
RUN case ",$ENGINES," in *,surya,*) \
      pip install --no-cache-dir --upgrade pip \
      && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu ;; \
    esac
RUN mkdir -p src/ocrhub && touch src/ocrhub/__init__.py \
    && pip install --no-cache-dir --upgrade pip \
    && if [ -n "$ENGINES" ]; then \
         pip install --no-cache-dir ".[$ENGINES]"; \
       else \
         pip install --no-cache-dir .; \
       fi

# Now the real source: reinstall just the package (deps already present).
COPY src ./src
RUN pip install --no-cache-dir --no-deps --force-reinstall .

RUN useradd --create-home --shell /bin/bash ocrhub \
    && mkdir -p /home/ocrhub/.cache /home/ocrhub/data \
    && chown -R ocrhub:ocrhub /app /home/ocrhub
USER ocrhub

EXPOSE 8000
CMD ["python", "-m", "ocrhub.main"]
