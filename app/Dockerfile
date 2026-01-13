FROM node:22-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY dist ./dist

EXPOSE 8000

CMD ["node", "dist/main.js"]
