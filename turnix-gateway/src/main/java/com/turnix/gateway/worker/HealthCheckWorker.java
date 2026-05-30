package com.turnix.gateway.worker;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * Worker programado del gateway.
 *
 * <p>Cada {@code worker.healthcheck.interval-ms} milisegundos lanza un GET
 * contra {@code ${BACKEND_URL}/api/health} y registra latencia y resultado
 * en el {@link MetricsStore}. Esto permite exponer en tiempo real el estado
 * del backend a traves de {@code GET /worker/stats}.</p>
 */
@Component
public class HealthCheckWorker {

    private static final Logger log = LoggerFactory.getLogger(HealthCheckWorker.class);

    private final WebClient backendClient;
    private final MetricsStore metrics;

    public HealthCheckWorker(MetricsStore metrics,
                             @Value("${BACKEND_URL:http://localhost:8001}") String backendUrl) {
        this.metrics = metrics;
        this.backendClient = WebClient.builder()
                .baseUrl(backendUrl)
                .build();
        log.info("Turnix worker inicializado contra backend={}", backendUrl);
    }

    @Scheduled(
        fixedDelayString = "${worker.healthcheck.interval-ms:15000}",
        initialDelayString = "${worker.healthcheck.initial-delay-ms:5000}"
    )
    public void pingBackend() {
        long t0 = System.nanoTime();
        backendClient.get()
            .uri("/api/health")
            .retrieve()
            .bodyToMono(String.class)
            .timeout(Duration.ofSeconds(5))
            .onErrorResume(err -> {
                long ms = (System.nanoTime() - t0) / 1_000_000L;
                log.warn("Worker: backend KO ({} ms): {}", ms, err.getMessage());
                metrics.recordBackendCheck(false, ms, "DOWN");
                return Mono.empty();
            })
            .doOnSuccess(body -> {
                if (body == null) return; // ya manejado en onErrorResume
                long ms = (System.nanoTime() - t0) / 1_000_000L;
                boolean ok = body.contains("\"db\":\"ok\"") || body.contains("UP");
                metrics.recordBackendCheck(ok, ms, ok ? "UP" : "DEGRADED");
                log.debug("Worker: backend {} ({} ms)", ok ? "OK" : "DEGRADED", ms);
            })
            .subscribe();
    }
}
