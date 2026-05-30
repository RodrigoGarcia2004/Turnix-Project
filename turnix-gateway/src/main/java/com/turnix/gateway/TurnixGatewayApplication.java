package com.turnix.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Punto de entrada del API Gateway de Turnix.
 *
 * Este servicio actua como puerta de entrada unica del sistema:
 * recibe el trafico HTTP/WebSocket de los clientes (paciente, medico, admin)
 * y lo enruta al backend FastAPI principal definido en {@code BACKEND_URL}.
 */
@SpringBootApplication
public class TurnixGatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(TurnixGatewayApplication.class, args);
    }
}
