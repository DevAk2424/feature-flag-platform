package com.akshayk.flagplatform.gateway;
import com.akshayk.flagplatform.common.Model.*;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.*;
import reactor.core.publisher.Flux;
import java.time.Duration;
@RestController @CrossOrigin
public class GatewayController {
    private final ConfigStore store; GatewayController(ConfigStore s){store=s;}
    @GetMapping("/api/config") public ConfigStore.Snapshot config(){ return store.snapshot(); }
    /** Internal event ingress used in the sandbox profile and tests to inject a
     *  config event exactly as the Kafka consumer would. In production the
     *  Kafka listener is the ingress; disable with gateway.internal-ingress.enabled=false. */
    @org.springframework.web.bind.annotation.PostMapping("/internal/events")
    public ConfigStore.Snapshot ingest(@org.springframework.web.bind.annotation.RequestBody FlagConfigEvent ev){ store.applyEvent(ev); return store.snapshot(); }
    @GetMapping("/api/flags") public java.util.List<Flag> flags(){ return store.snapshot().flags(); }
    /** SSE stream: snapshot first, then live deltas, with heartbeat comments.
     *  Clients (SDKs / dashboard) keep ONE open connection instead of polling REST. */
    @GetMapping(value="/stream/config", produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<Object>> stream(){
        Flux<ServerSentEvent<Object>> snapshot = Flux.just(ServerSentEvent.builder((Object)store.snapshot()).event("snapshot").build());
        Flux<ServerSentEvent<Object>> deltas = store.deltas().map(ev->ServerSentEvent.builder((Object)ev).event("flag-config").id(String.valueOf(ev.configVersion())).build());
        Flux<ServerSentEvent<Object>> heartbeat = Flux.interval(Duration.ofSeconds(15)).map(i->ServerSentEvent.builder().comment("heartbeat").build());
        return Flux.merge(snapshot.concatWith(deltas), heartbeat);
    }
}
