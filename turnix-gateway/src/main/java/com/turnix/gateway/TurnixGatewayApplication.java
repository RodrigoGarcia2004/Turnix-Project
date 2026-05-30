package com.turnix.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Punto de entrada del API Gateway de Turnix.
 *
 * Este servicio actua como puerta de entrada unica del sistema:
 * recibe el trafico HTTP/WebSocket de los clientes (paciente, medico, admin)
 * y lo enruta al backend FastAPI principal definido en {@code BACKEND_URL}.
 *
 * {@code @EnableScheduling} activa el worker programado que cada N segundos
 * hace un healthcheck al backend y publica las metricas en {@code /worker/stats}.
 */
@SpringBootApplication
@EnableScheduling
public class TurnixGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(TurnixGatewayApplication.class, args);
    }
}
