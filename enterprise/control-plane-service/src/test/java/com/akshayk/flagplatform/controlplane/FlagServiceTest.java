package com.akshayk.flagplatform.controlplane;
import com.akshayk.flagplatform.common.*;
import com.akshayk.flagplatform.common.Model.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
@SpringBootTest @AutoConfigureMockMvc
class FlagServiceTest {
    @Autowired FlagService svc; @Autowired FlagEventBus bus; @Autowired MockMvc mvc;
    @Test void createIncrementsVersionAndAudits(){
        Flag f = svc.create(Flag.simple("t-create-"+System.nanoTime(), 10), "tester");
        assertEquals(1, f.version());
        Flag r = svc.patchRollout(f.key(), 25, "tester");
        assertEquals(2, r.version()); assertEquals(25, r.fallthroughPercentage());
        assertTrue(svc.audit().stream().anyMatch(a->a.flagKey.equals(f.key()) && a.action.equals("ROLLOUT")));
    }
    @Test void killSwitchEvaluatesOff(){
        Flag f = svc.create(Flag.simple("t-kill-"+System.nanoTime(), 100), "tester");
        svc.setEnabled(f.key(), false, "tester");
        var res = Evaluator.evaluate(svc.get(f.key()), EvalContext.of("anyone"), false);
        assertEquals(Evaluator.KILL_SWITCH, res.reason());
    }
    @Test void rollbackRestoresAsForwardVersion(){
        Flag f = svc.create(Flag.simple("t-rb-"+System.nanoTime(), 10), "tester");
        svc.patchRollout(f.key(), 80, "tester");
        Flag back = svc.rollback(f.key(), 1, "tester");
        assertEquals(10, back.fallthroughPercentage()); assertEquals(3, back.version());
    }
    @Test void mutationPublishesStreamingEvent() throws Exception {
        var events = new java.util.concurrent.CopyOnWriteArrayList<FlagConfigEvent>();
        var sub = bus.flux().subscribe(events::add);
        Flag f = svc.create(Flag.simple("t-ev-"+System.nanoTime(), 5), "tester");
        svc.patchRollout(f.key(), 15, "tester");
        Thread.sleep(200); sub.dispose();
        assertTrue(events.stream().anyMatch(e->e.flagKey().equals(f.key()) && e.type().equals("ROLLOUT")), events.toString());
    }
    @Test void approvedCommandEventAppliesRollout(){
        Flag f = svc.create(Flag.simple("t-cmd-"+System.nanoTime(), 10), "tester");
        Flag out = svc.applyCommand(new FlagCommandEvent("c1","SET_ROLLOUT", f.key(), 0.0, null, "akshay", "prop-1", System.currentTimeMillis()));
        assertEquals(0, out.fallthroughPercentage());
        assertTrue(svc.audit().stream().anyMatch(a->a.actor.contains("risk-agent-approved-by:akshay")));
    }
    @Test void snapshotEndpoint() throws Exception {
        mvc.perform(get("/api/config/snapshot")).andExpect(status().isOk()).andExpect(jsonPath("$.configVersion").exists()).andExpect(jsonPath("$.flags").isArray());
        mvc.perform(get("/actuator/health")).andExpect(status().isOk());
    }
}
