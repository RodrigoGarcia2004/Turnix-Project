package com.turnix.gateway.worker;

import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.LongAdder;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Controlador que expone las metricas del gateway como JSON publico.
 *
 * <p>Endpoint disponible en {@code GET /worker/stats}. Pensado para ser
 * consultado desde el navegador o desde herramientas tipo curl/Postman
 * sin necesidad de autenticacion (es informacion no sensible).</p>
 */
@RestController
@RequestMapping("/worker")
public class WorkerStatsController {

    private final MetricsStore metrics;

    public WorkerStatsController(MetricsStore metrics) {
        this.metrics = metrics;
    }

    @GetMapping(value = "/stats", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> stats() {
        long uptimeMs = System.currentTimeMillis() - metrics.getStartedAt();

        Map<String, Object> root = new LinkedHashMap<>();
        root.put("service", "turnix-gateway");
        root.put("started_at", metrics.getStartedAtInstant().toString());
        root.put("uptime_seconds", uptimeMs / 1000L);
        root.put("uptime_human", humanize(Duration.ofMillis(uptimeMs)));
        root.put("total_requests", metrics.getTotalRequests());
        root.put("requests_by_route", toIntMap(metrics.getRequestsByRoute()));
        root.put("responses_by_status_class", toIntMap(metrics.getResponsesByStatusClass()));

        Map<String, Object> backend = new LinkedHashMap<>();
        backend.put("status", metrics.getLastBackendStatus());
        long last = metrics.getLastBackendCheckMs();
        backend.put("last_check_at", last > 0 ? Instant.ofEpochMilli(last).toString() : null);
        backend.put("last_latency_ms", metrics.getLastBackendLatencyMs());
        backend.put("checks_ok", metrics.getBackendChecksOk());
        backend.put("checks_fail", metrics.getBackendChecksFail());
        root.put("backend", backend);

        return root;
    }

    /** Devuelve solo "UP" / "DOWN" / "UNKNOWN" para sondas externas. */
    @GetMapping(value = "/health", produces = MediaType.APPLICATION_JSON_VALUE)
    public Map<String, Object> health() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("gateway", "UP");
        out.put("backend", metrics.getLastBackendStatus());
        return out;
    }

    // ===== Helpers =====
    private static Map<String, Long> toIntMap(Map<String, LongAdder> src) {
        Map<String, Long> out = new LinkedHashMap<>();
        src.forEach((k, v) -> out.put(k, v.sum()));
        return out;
    }

    private static String humanize(Duration d) {
        long s = d.getSeconds();
        long days  = s / 86400; s %= 86400;
        long hours = s / 3600;  s %= 3600;
        long mins  = s / 60;    s %= 60;
        StringBuilder sb = new StringBuilder();
        if (days  > 0) sb.append(days).append("d ");
        if (hours > 0) sb.append(hours).append("h ");
        if (mins  > 0) sb.append(mins).append("m ");
        sb.append(s).append("s");
        return sb.toString();
    }
}
