package com.akshayk.flagplatform.gateway;
import com.akshayk.flagplatform.common.Model.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.reactive.server.WebTestClient;
import reactor.test.StepVerifier;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;
@SpringBootTest(properties={"gateway.subscribe.enabled=false"})
class GatewayStreamTest {
    @Autowired ConfigStore store; @Autowired GatewayController controller; @Autowired org.springframework.context.ApplicationContext ctx;
    WebTestClient client(){ return WebTestClient.bindToApplicationContext(ctx).build(); }
    @Test void streamEmitsSnapshotThenDelta(){
        store.loadSnapshot(1, List.of(Flag.simple("checkout-redesign",10)));
        var flux = controller.stream();
        StepVerifier.create(flux.take(2))
            .assertNext(sse->{ assertEquals("snapshot", sse.event()); assertTrue(String.valueOf(sse.data()).contains("checkout-redesign")); })
            .then(()-> store.applyEvent(new FlagConfigEvent("e1","ROLLOUT",2,"tester",System.currentTimeMillis(), Flag.simple("checkout-redesign",50), "checkout-redesign")))
            .assertNext(sse->{ assertEquals("flag-config", sse.event()); })
            .verifyComplete();
    }
    @Test void apiServesLastKnownGoodSnapshot(){
        store.loadSnapshot(7, List.of(Flag.simple("ai-recs",25)));
        store.markDisconnected();
        client().get().uri("/api/config").exchange().expectStatus().isOk()
            .expectBody().jsonPath("$.configVersion").isEqualTo(7).jsonPath("$.stale").isEqualTo(true).jsonPath("$.flags[0].key").isEqualTo("ai-recs");
    }
    @Test void sseEndpointContentType(){
        client().get().uri("/stream/config").accept(MediaType.TEXT_EVENT_STREAM).exchange().expectStatus().isOk()
            .expectHeader().contentTypeCompatibleWith(MediaType.TEXT_EVENT_STREAM);
    }
}
