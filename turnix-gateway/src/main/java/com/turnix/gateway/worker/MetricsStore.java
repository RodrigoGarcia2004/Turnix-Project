package com.turnix.gateway.worker;

import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.LongAdder;
import org.springframework.stereotype.Component;

/**
 * Almacen en memoria de las metricas del worker y del filtro de peticiones.
 *
 * <p>Es thread-safe (LongAdder/ConcurrentHashMap/AtomicLong) porque tanto el
 * worker programado como las peticiones concurrentes que atraviesan el gateway
 * escriben aqui simultaneamente.</p>
 */
@Component
public class MetricsStore {

    /** Instante (epoch ms) en que arranco el gateway. */
    private final long startedAt = System.currentTimeMillis();

    /** Numero total de peticiones HTTP procesadas por el gateway. */
    private final LongAdder totalRequests = new LongAdder();

    /** Contador de peticiones por prefijo de ruta (/api, /ws, otros). */
    private final Map<String, LongAdder> requestsByRoute = new ConcurrentHashMap<>();

    /** Codigos de respuesta agrupados (2xx, 3xx, 4xx, 5xx). */
    private final Map<String, LongAdder> responsesByStatusClass = new ConcurrentHashMap<>();

    // ===== Salud del backend medida por el worker =====
    private final AtomicLong lastBackendCheckMs = new AtomicLong(0);
    private final AtomicLong lastBackendLatencyMs = new AtomicLong(-1);
    private volatile String lastBackendStatus = "UNKNOWN";
    private final LongAdder backendChecksOk = new LongAdder();
    private final LongAdder backendChecksFail = new LongAdder();

    // ===== Mutators usados por el filtro =====
    public void recordRequest(String routeKey, int statusCode) {
        totalRequests.increment();
        requestsByRoute.computeIfAbsent(routeKey, k -> new LongAdder()).increment();
        String klass = (statusCode / 100) + "xx";
        responsesByStatusClass.computeIfAbsent(klass, k -> new LongAdder()).increment();
    }

    // ===== Mutators usados por el worker =====
    public void recordBackendCheck(boolean ok, long latencyMs, String status) {
        lastBackendCheckMs.set(System.currentTimeMillis());
        lastBackendLatencyMs.set(latencyMs);
        lastBackendStatus = status;
        if (ok) {
            backendChecksOk.increment();
        } else {
            backendChecksFail.increment();
        }
    }

    // ===== Getters (snapshot inmutable para el JSON) =====
    public long getStartedAt()             { return startedAt; }
    public long getTotalRequests()         { return totalRequests.sum(); }
    public Map<String, LongAdder> getRequestsByRoute()      { return requestsByRoute; }
    public Map<String, LongAdder> getResponsesByStatusClass() { return responsesByStatusClass; }
    public long getLastBackendCheckMs()    { return lastBackendCheckMs.get(); }
    public long getLastBackendLatencyMs()  { return lastBackendLatencyMs.get(); }
    public String getLastBackendStatus()   { return lastBackendStatus; }
    public long getBackendChecksOk()       { return backendChecksOk.sum(); }
    public long getBackendChecksFail()     { return backendChecksFail.sum(); }
    public Instant getStartedAtInstant()   { return Instant.ofEpochMilli(startedAt); }
}
