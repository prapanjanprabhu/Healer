FROM python:3.12-slim

WORKDIR /app

# nginx: the one central Nginx installation this service is colocated with
# and exclusively permitted to manage (app/services/nginx_manager.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nginx \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /etc/nginx/conf.d/healer \
    && cp nginx/healer-managed.conf /etc/nginx/conf.d/healer-managed.conf \
    && chmod +x docker-entrypoint.sh

# Intentionally not published beyond the internal network — see
# docs/security-boundaries.md. docker-compose only starts this service under
# the "gateway" profile. 80/443 are Nginx's own listeners, proxying to
# whichever managed applications currently have healthy instances.
EXPOSE 8100 80 443

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD curl -f http://localhost:8100/health || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
