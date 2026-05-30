# Turnix Gateway

API Gateway (puerta de entrada unica) del sistema **Turnix Salud**.

Construido sobre **Spring Cloud Gateway** y empaquetado en un contenedor Docker
basado en JRE 21. Recibe todo el trafico HTTP y WebSocket de los clientes
(paciente, medico, admin) y lo enruta al backend FastAPI principal.

## Arquitectura

```
                +-----------------+
  Cliente  ---> | Turnix Gateway  | --(HTTP/WS)--> Backend FastAPI (Supabase Postgres)
   (HTTP/WS)    | (Spring Cloud)  |
                +-----------------+
```

## Stack

- Java 21 (Eclipse Temurin)
- Spring Boot 3.3
- Spring Cloud Gateway 2023.0.x
- Docker multistage (Maven + JRE Alpine)

## Rutas

| Patron       | Destino                       | Notas                       |
| ------------ | ----------------------------- | --------------------------- |
| `/api/**`    | `${BACKEND_URL}`              | REST API del backend        |
| `/ws/**`     | `${BACKEND_URL_WS}`           | WebSocket (chat, turnos)    |
| `/**`        | `${BACKEND_URL}`              | Frontend estatico (HTML/JS) |
| `/actuator/health` | (local)                | Healthcheck Spring Actuator |

## Variables de entorno

| Variable         | Default                  | Descripcion                                      |
| ---------------- | ------------------------ | ------------------------------------------------ |
| `PORT`           | `8080`                   | Puerto de escucha del gateway                    |
| `BACKEND_URL`    | `http://localhost:8001`  | URL del backend FastAPI                          |
| `BACKEND_URL_WS` | `ws://localhost:8001`    | URL WebSocket del backend (esquema `ws://`)      |

## Ejecutar en local

Requisitos: JDK 21 y Maven 3.9+.

```bash
cd turnix-gateway
mvn spring-boot:run
```

Pruebas rapidas:

```bash
curl http://localhost:8080/actuator/health
curl http://localhost:8080/api/health
```

## Build y ejecucion con Docker

```bash
docker build -t turnix-gateway .
docker run --rm -p 8080:8080 \
  -e BACKEND_URL=http://host.docker.internal:8001 \
  -e BACKEND_URL_WS=ws://host.docker.internal:8001 \
  turnix-gateway
```

## Despliegue en Render

El servicio `turnix-gateway` en Render esta configurado como **Docker** con
`rootDir = turnix-gateway`. Render construye automaticamente la imagen a partir
del `Dockerfile` de esta carpeta tras cada push a la rama configurada.

Variables a definir en el dashboard de Render para este servicio:

- `BACKEND_URL`    -> URL publica del servicio backend (p.ej. `https://turnix-project.onrender.com`)
- `BACKEND_URL_WS` -> Igual que el anterior pero con esquema `wss://`
