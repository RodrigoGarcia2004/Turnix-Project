package com.turnix.gateway.worker;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * Filtro global que cuenta cada peticion que atraviesa el gateway.
 *
 * <p>Se ejecuta al final de la cadena (despues de que el backend haya respondido)
 * y registra en {@link MetricsStore}:</p>
 * <ul>
 *   <li>Clave de ruta (/api, /ws, /worker u other).</li>
 *   <li>Clase de status (2xx, 3xx, 4xx, 5xx).</li>
 * </ul>
 */
@Component
public class RequestCountingFilter implements GlobalFilter, Ordered {

    private final MetricsStore metrics;

    public RequestCountingFilter(MetricsStore metrics) {
        this.metrics = metrics;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String path = exchange.getRequest().getURI().getPath();
        String routeKey = classify(path);

        return chain.filter(exchange).doFinally(sig -> {
            HttpStatus status = HttpStatus.resolve(
                exchange.getResponse().getStatusCode() != null
                    ? exchange.getResponse().getStatusCode().value()
                    : 0
            );
            int code = (status != null) ? status.value() : 0;
            metrics.recordRequest(routeKey, code);
        });
    }

    private static String classify(String path) {
        if (path == null) return "other";
        if (path.startsWith("/api"))    return "/api";
        if (path.startsWith("/ws"))     return "/ws";
        if (path.startsWith("/worker")) return "/worker";
        if (path.startsWith("/actuator")) return "/actuator";
        return "other";
    }

    /** Se coloca al inicio para envolver toda la cadena. */
    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE;
    }
}
