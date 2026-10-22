package com.akshayk.flagplatform.controlplane;
import com.akshayk.flagplatform.common.Model.FlagConfigEvent;
import org.springframework.context.annotation.Profile;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;
import com.fasterxml.jackson.databind.ObjectMapper;
/** Streaming bus abstraction. Sandbox: in-process reactive stream (also exposed
 *  as an internal SSE event feed the gateway subscribes to). Prod: Kafka topic. */
interface FlagEventPublisher { void publish(FlagConfigEvent e); }
@Component
class FlagEventBus {
    private final Sinks.Many<FlagConfigEvent> sink = Sinks.many().multicast().onBackpressureBuffer(1024, false);
    public void emit(FlagConfigEvent e){ sink.tryEmitNext(e); }
    public Flux<FlagConfigEvent> flux(){ return sink.asFlux(); }
}
@Component @Profile("!prod")
class InProcessFlagEventPublisher implements FlagEventPublisher {
    private final FlagEventBus bus; InProcessFlagEventPublisher(FlagEventBus b){bus=b;}
    public void publish(FlagConfigEvent e){ bus.emit(e); }
}
@Component @Profile("prod")
class KafkaFlagEventPublisher implements FlagEventPublisher {
    private final KafkaTemplate<String,String> kafka; private final ObjectMapper json; private final FlagEventBus bus;
    KafkaFlagEventPublisher(KafkaTemplate<String,String> k, ObjectMapper j, FlagEventBus b){kafka=k;json=j;bus=b;}
    public void publish(FlagConfigEvent e){
        bus.emit(e);
        try{ kafka.send("flag-config-events", e.flagKey(), json.writeValueAsString(e)); }
        catch(Exception ex){ throw new IllegalStateException("kafka publish failed", ex); }
    }
}
