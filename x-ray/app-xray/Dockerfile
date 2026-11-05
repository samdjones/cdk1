# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src/ ./src/
RUN npm run build

# Remove devDependencies for production
RUN npm prune --production

# ---- Runtime stage ----
FROM node:22-alpine AS runtime

WORKDIR /app

# Copy built artifacts and production node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./
COPY otel-bootstrap.js ./

# OTEL auto-instrumentation via ADOT agent, wrapped by otel-bootstrap.js to
# give the ECS task-credentials HTTP call a readable X-Ray span name
ENV NODE_OPTIONS="--require /app/otel-bootstrap.js"

# CloudWatch Agent sidecar endpoint - Application Signals traces + metrics
# (localhost since containers share network in Fargate awsvpc mode)
ENV OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
ENV OTEL_EXPORTER_OTLP_TRACES_ENDPOINT="http://localhost:4316/v1/traces"
ENV OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT="http://localhost:4316/v1/metrics"
ENV OTEL_METRICS_EXPORTER="none"
ENV OTEL_LOGS_EXPORTER="none"
ENV OTEL_TRACES_SAMPLER="xray"
ENV OTEL_TRACES_SAMPLER_ARG="endpoint=http://localhost:2000"
ENV OTEL_AWS_APPLICATION_SIGNALS_ENABLED="true"

# Service name for traces
ENV OTEL_SERVICE_NAME="xray-frontend"

# X-Ray daemon address (OTEL collector handles X-Ray export, but set for SDK awareness)
ENV AWS_XRAY_DAEMON_ADDRESS="localhost:2000"

# Propagate trace context using X-Ray format
ENV OTEL_PROPAGATORS="xray"

EXPOSE 8000

CMD ["node", "dist/main.js"]
