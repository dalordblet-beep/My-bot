# Username Scanner Bot - production image.
#
# The bot uses long polling, so no inbound port is exposed and no domain is
# needed. Configuration comes from the environment (see .env.example); nothing
# secret is baked into the image.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUTF8=1

WORKDIR /app

# Dependencies first, so the layer is cached across code changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The MTProto session (if used) lives outside the image, on a mounted volume,
# so a redeploy does not lose it. Override MTPROTO_SESSION to point at it.
CMD ["python", "-m", "app.main"]
