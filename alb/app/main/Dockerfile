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

EXPOSE 8000

CMD ["node", "dist/main.js"]
