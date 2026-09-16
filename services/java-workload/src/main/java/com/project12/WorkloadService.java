package com.project12;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import javax.management.MBeanServer;
import javax.management.ObjectName;
import javax.management.StandardMBean;

import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

public class WorkloadService {

    public interface WorkloadMetricsMBean {
        String getScenario();

        long getRequestCount();

        double getErrorRate();

        double getLatencyMs();

        long getConsumerLag();

        long getAuthenticationFailures();

        long getTlsFailures();

        double getDatabaseLatencyMs();

        long getRetryCount();

        int getQueueDepth();
    }

    public static class WorkloadMetrics implements WorkloadMetricsMBean {

        private volatile String scenario = "normal";

        private volatile long requestCount = 0;
        private volatile double errorRate = 0.005;
        private volatile double latencyMs = 120.0;
        private volatile long consumerLag = 20;
        private volatile long authenticationFailures = 0;
        private volatile long tlsFailures = 0;
        private volatile double databaseLatencyMs = 15.0;
        private volatile long retryCount = 0;
        private volatile int queueDepth = 5;

        private final List<byte[]> retainedMemory =
                Collections.synchronizedList(new ArrayList<>());

        @Override
        public String getScenario() {
            return scenario;
        }

        @Override
        public long getRequestCount() {
            return requestCount;
        }

        @Override
        public double getErrorRate() {
            return errorRate;
        }

        @Override
        public double getLatencyMs() {
            return latencyMs;
        }

        @Override
        public long getConsumerLag() {
            return consumerLag;
        }

        @Override
        public long getAuthenticationFailures() {
            return authenticationFailures;
        }

        @Override
        public long getTlsFailures() {
            return tlsFailures;
        }

        @Override
        public double getDatabaseLatencyMs() {
            return databaseLatencyMs;
        }

        @Override
        public long getRetryCount() {
            return retryCount;
        }

        @Override
        public int getQueueDepth() {
            return queueDepth;
        }

        public synchronized void setScenario(String newScenario) {

            scenario = newScenario;

            errorRate = 0.005;
            latencyMs = 120.0;
            consumerLag = 20;
            databaseLatencyMs = 15.0;
            queueDepth = 5;

            retainedMemory.clear();

            switch (newScenario) {

                case "normal":
                    break;

                case "memory_pressure":
                    latencyMs = 350.0;
                    queueDepth = 25;
                    break;

                case "gc_storm":
                    latencyMs = 700.0;
                    errorRate = 0.03;
                    break;

                case "consumer_lag":
                    consumerLag = 10000;
                    queueDepth = 200;
                    latencyMs = 650.0;
                    break;

                case "tls_failure":
                    errorRate = 0.18;
                    latencyMs = 2800.0;
                    break;

                case "auth_failure":
                    errorRate = 0.22;
                    latencyMs = 900.0;
                    break;

                case "db_latency":
                    databaseLatencyMs = 1800.0;
                    latencyMs = 2200.0;
                    queueDepth = 120;
                    break;

                case "retry_storm":
                    errorRate = 0.12;
                    latencyMs = 1900.0;
                    queueDepth = 180;
                    break;

                default:
                    scenario = "normal";
                    break;
            }
        }

        public void tick() {

            requestCount += 100;

            switch (scenario) {

                case "normal":
                    consumerLag = Math.max(10, consumerLag - 5);
                    queueDepth = 5;
                    break;

                case "memory_pressure":

                    if (retainedMemory.size() < 96) {
                        retainedMemory.add(new byte[1024 * 1024]);
                    }

                    latencyMs += 4;
                    queueDepth += 1;
                    break;

                case "gc_storm":

                    byte[][] temporaryPressure = new byte[8][];

                    for (int i = 0; i < temporaryPressure.length; i++) {
                        temporaryPressure[i] =
                                new byte[1024 * 1024];
                    }

                    retryCount += 3;
                    break;

                case "consumer_lag":
                    consumerLag += 1200;
                    queueDepth += 20;
                    break;

                case "tls_failure":
                    tlsFailures += 45;
                    retryCount += 30;
                    consumerLag += 800;
                    queueDepth += 15;
                    break;

                case "auth_failure":
                    authenticationFailures += 50;
                    retryCount += 15;
                    break;

                case "db_latency":
                    retryCount += 20;
                    queueDepth += 25;
                    consumerLag += 400;
                    break;

                case "retry_storm":
                    retryCount += 100;
                    queueDepth += 40;
                    consumerLag += 600;
                    break;

                default:
                    break;
            }
        }

        public String toJson() {

            return "{"
                    + "\"scenario\":\"" + scenario + "\","
                    + "\"request_count\":" + requestCount + ","
                    + "\"error_rate\":" + errorRate + ","
                    + "\"latency_ms\":" + latencyMs + ","
                    + "\"consumer_lag\":" + consumerLag + ","
                    + "\"authentication_failures\":"
                    + authenticationFailures + ","
                    + "\"tls_failures\":" + tlsFailures + ","
                    + "\"database_latency_ms\":"
                    + databaseLatencyMs + ","
                    + "\"retry_count\":" + retryCount + ","
                    + "\"queue_depth\":" + queueDepth
                    + "}";
        }
    }

    private static void respond(
            HttpExchange exchange,
            int status,
            String body) throws IOException {

        byte[] payload =
                body.getBytes(StandardCharsets.UTF_8);

        exchange.getResponseHeaders().set(
                "Content-Type",
                "application/json"
        );

        exchange.sendResponseHeaders(
                status,
                payload.length
        );

        exchange.getResponseBody().write(payload);
        exchange.close();
    }

    private static String getQueryParameter(
            URI uri,
            String target) {

        String query = uri.getRawQuery();

        if (query == null) {
            return null;
        }

        for (String pair : query.split("&")) {

            String[] parts =
                    pair.split("=", 2);

            if (parts.length == 2
                    && parts[0].equals(target)) {

                return URLDecoder.decode(
                        parts[1],
                        StandardCharsets.UTF_8
                );
            }
        }

        return null;
    }

    public static void main(String[] args)
            throws Exception {

        WorkloadMetrics metrics =
                new WorkloadMetrics();

        MBeanServer mBeanServer =
                ManagementFactory
                        .getPlatformMBeanServer();

        ObjectName objectName =
                new ObjectName(
                        "com.project12:type=WorkloadMetrics"
                );

        StandardMBean standardMBean =
                new StandardMBean(
                        metrics,
                        WorkloadMetricsMBean.class
                );

        mBeanServer.registerMBean(
                standardMBean,
                objectName
        );

        ScheduledExecutorService scheduler =
                Executors.newSingleThreadScheduledExecutor();

        scheduler.scheduleAtFixedRate(
                metrics::tick,
                0,
                1,
                TimeUnit.SECONDS
        );

        HttpServer httpServer =
                HttpServer.create(
                        new InetSocketAddress(
                                "127.0.0.1",
                                8080
                        ),
                        0
                );

        httpServer.createContext(
                "/health",
                exchange ->
                        respond(
                                exchange,
                                200,
                                "{\"status\":\"UP\"}"
                        )
        );

        httpServer.createContext(
                "/state",
                exchange ->
                        respond(
                                exchange,
                                200,
                                metrics.toJson()
                        )
        );

        httpServer.createContext(
                "/scenario",
                exchange -> {

                    String scenario =
                            getQueryParameter(
                                    exchange.getRequestURI(),
                                    "name"
                            );

                    if (scenario == null
                            || scenario.isBlank()) {

                        respond(
                                exchange,
                                400,
                                "{\"error\":\"missing scenario name\"}"
                        );

                        return;
                    }

                    metrics.setScenario(scenario);

                    respond(
                            exchange,
                            200,
                            metrics.toJson()
                    );
                }
        );

        httpServer.setExecutor(
                Executors.newFixedThreadPool(4)
        );

        httpServer.start();

        System.out.println(
                "PROJECT12_WORKLOAD=STARTED"
        );

        System.out.println(
                "HTTP=http://127.0.0.1:8080"
        );

        System.out.println(
                "JMX_OBJECT=com.project12:type=WorkloadMetrics"
        );
    }
}
