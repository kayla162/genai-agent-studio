# api 與 worker 共用的映像檔（compose 以不同的指令啟動）
FROM public.ecr.aws/docker/library/python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

# 先編譯位元組碼；使用映像檔內的 Python 3.13，不讓 uv 另外下載
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

# 程式在 /app/backend，設定推算的 repo 根目錄為 /app（brands/、data/、assets/products/ 由 compose 掛載）
WORKDIR /app/backend
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
ENV PATH="/app/backend/.venv/bin:$PATH"

# 以 app 使用者執行（不是 root）。進入點先把 data/ 與 models/ 交給 app 再降權限，
# 舊版以 root 建立的 volume 也能沿用；新建的 volume 沿用這裡的擁有者
RUN useradd --create-home --uid 1000 app     && mkdir -p /app/data /app/models     && chown app:app /app/data /app/models
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]

EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
