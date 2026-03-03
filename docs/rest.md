# Cadis Docker / REST Mode

## Run with Docker

```bash
docker build -t cadis:latest .
docker run --rm -p 8080:8080 cadis:latest
```

Server entrypoint: `cadisd`.

## Endpoints

- `GET /health`
- `GET /info`
- `POST /lookup`
- `POST /bootstrap`
- `POST /reinstall`

## Lookup Request

```json
{
  "lat": 24.5674,
  "lon": 121.0258,
  "mode": "lazy",
  "auto_update": true
}
```

### `mode`

- `lazy` (default): auto-sync supported country dataset, then retry lookup.
- `strict`: no implicit sync.

## Curl Examples

```bash
curl -s http://127.0.0.1:8080/health | jq
```

```bash
curl -s -X POST http://127.0.0.1:8080/lookup \
  -H "Content-Type: application/json" \
  -d '{"lat":24.567439426864148,"lon":121.02576600335526}' | jq
```

```bash
curl -s -X POST http://127.0.0.1:8080/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"iso2":"TW","update_to_latest":true}' | jq
```

## Response Policy

- REST responses are sanitized for remote use.


