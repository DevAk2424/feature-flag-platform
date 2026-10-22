package com.akshayk.flagplatform.gateway;
import com.akshayk.flagplatform.common.Model.*;
import com.fasterxml.jackson.databind.*;
import org.slf4j.*; import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Profile; import org.springframework.context.event.EventListener;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono; import reactor.util.retry.Retry;
import java.time.Duration; import java.util.List;
/** Sandbox transport: subscribe to the control plane's internal SSE event feed.
 *  Bootstrap = one snapshot fetch, then a pure stream of deltas (no polling). */
@Component @Profile("!prod")
class SandboxStreamClient {
    private static final Logger log = LoggerFactory.getLogger(SandboxStreamClient.class);
    private final ConfigStore store; private final ObjectMapper json; private final WebClient http;
    private final boolean enabled;
    SandboxStreamClient(ConfigStore s, ObjectMapper j, @Value("${gateway.control-plane-url:http://localhost:8080}") String base,
                        @Value("${gateway.subscribe.enabled:true}") boolean enabled){
        store=s; json=j; this.enabled=enabled; http=WebClient.builder().baseUrl(base).codecs(c->c.defaultCodecs().maxInMemorySize(4*1024*1024)).build();
    }
    @EventListener(ApplicationReadyEvent.class) public void start(){
        if(!enabled){ log.info("gateway subscription disabled"); return; }
        bootstrapAndSubscribe();
    }
    void bootstrapAndSubscribe(){
        http.get().uri("/api/config/snapshot?env=prod").retrieve().bodyToMono(JsonNode.class)
            .doOnNext(node->{
                try{ List<Flag> flags = List.of(json.treeToValue(node.path("flags"), Flag[].class));
                     store.loadSnapshot(node.path("configVersion").asLong(0), flags);
                     log.info("gateway loaded snapshot v{} ({} flags)", node.path("configVersion").asLong(), flags.size());
                }catch(Exception e){ log.warn("snapshot parse failed", e); }
            })
            .doOnError(e->{ store.markDisconnected(); log.warn("control plane snapshot unavailable ({}), serving last-known-good", e.getMessage()); })
            .onErrorResume(e->Mono.empty())
            .thenMany(http.get().uri("/internal/config-events").retrieve()
                .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>(){})
                .flatMap(sse->{ try{ return Mono.just(json.readValue(sse.data(), FlagConfigEvent.class)); }catch(Exception e){ return Mono.empty(); } })
                .doOnNext(store::applyEvent)
                .doOnError(e->{ store.markDisconnected(); log.warn("config event stream dropped: {}", e.getMessage()); }))
            .retryWhen(Retry.backoff(Long.MAX_VALUE, Duration.ofSeconds(2)).maxBackoff(Duration.ofSeconds(15)))
            .subscribe();
    }
}
/** Production transport: Kafka consumer for flag-config-events. */
@Component @Profile("prod")
class KafkaStreamConsumer {
    private final ConfigStore store; private final ObjectMapper json;
    KafkaStreamConsumer(ConfigStore s, ObjectMapper j){store=s;json=j;}
    @KafkaListener(topics="flag-config-events", groupId="streaming-gateway")
    public void onEvent(String payload) throws Exception { store.applyEvent(json.readValue(payload, FlagConfigEvent.class)); }
}
