# Express app

## Local dev

From this directory:

```bash
npm install
npm run build
npm start
```

For development with hot reload:

```bash
npm install
npm run dev
```

App:

- `GET /health`

Run tests:

```bash
npm test
```

Build:

```bash
npm run build
```

## Docker

From this directory:

```bash
npm run build
docker build -t cdk1-app:local .
docker run --rm -p 8000:8000 cdk1-app:local
```
