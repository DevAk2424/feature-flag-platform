package com.akshayk.flagplatform.controlplane;
import com.akshayk.flagplatform.common.Model.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Profile;
import org.springframework.http.*; import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.*;
@RestController @RequestMapping("/api/flags") @CrossOrigin
class FlagController {
    private final FlagService svc; FlagController(FlagService s){svc=s;}
    record RolloutReq(double percentage, String actor){}
    record EnabledReq(boolean enabled, String actor){}
    record RollbackReq(long version, String actor){}
    @GetMapping public List<Flag> list(@RequestParam(required=false) String env){ return svc.list(env); }
    @GetMapping("/{key}") public Flag get(@PathVariable String key){ return svc.get(key); }
    @PostMapping public ResponseEntity<Flag> create(@RequestBody Flag f, @RequestHeader(value="x-actor",defaultValue="dashboard") String actor){ return ResponseEntity.status(HttpStatus.CREATED).body(svc.create(f,actor)); }
    @PutMapping("/{key}") public Flag update(@PathVariable String key,@RequestBody Flag f,@RequestHeader(value="x-actor",defaultValue="dashboard") String actor){ return svc.update(key,f,actor); }
    @PatchMapping("/{key}/rollout") public Flag rollout(@PathVariable String key,@RequestBody RolloutReq r){ return svc.patchRollout(key,r.percentage(), r.actor()==null?"dashboard":r.actor()); }
    @PostMapping("/{key}/kill-switch") public Flag kill(@PathVariable String key,@RequestBody EnabledReq r){ return svc.setEnabled(key, false, r.actor()==null?"dashboard":r.actor()); }
    @PostMapping("/{key}/enable") public Flag enable(@PathVariable String key,@RequestBody EnabledReq r){ return svc.setEnabled(key, true, r.actor()==null?"dashboard":r.actor()); }
    @PostMapping("/{key}/rollback") public Flag rollback(@PathVariable String key,@RequestBody RollbackReq r){ return svc.rollback(key,r.version(), r.actor()==null?"dashboard":r.actor()); }
    @GetMapping("/{key}/history") public List<Map<String,Object>> hist(@PathVariable String key){ return svc.history(key).stream().map(h->Map.<String,Object>of("flagKey",h.flagKey,"version",h.version,"ts",h.ts,"payload",h.payload)).toList(); }
    @ExceptionHandler({NoSuchElementException.class}) ResponseEntity<Map<String,String>> nf(Exception e){ return ResponseEntity.status(404).body(Map.of("error",String.valueOf(e.getMessage()))); }
    @ExceptionHandler({IllegalArgumentException.class}) ResponseEntity<Map<String,String>> bad(Exception e){ return ResponseEntity.status(400).body(Map.of("error",String.valueOf(e.getMessage()))); }
}
@RestController @CrossOrigin
class ConfigAndAuditController {
    private final FlagService svc; ConfigAndAuditController(FlagService s){svc=s;}
    @GetMapping("/api/config/snapshot") public Map<String,Object> snapshot(@RequestParam(defaultValue="prod") String env){
        return Map.of("configVersion", svc.configVersion(), "environment", env, "flags", svc.list(env), "generatedAtEpochMs", System.currentTimeMillis());
    }
    @GetMapping("/api/audit") public List<Map<String,Object>> audit(){ return svc.audit().stream().map(a->Map.<String,Object>of("id",a.id,"flagKey",a.flagKey,"actor",a.actor,"action",a.action,"version",a.version==null?0:a.version,"ts",a.ts)).toList(); }
    /** Streaming command ingress (sandbox transport for the flag-commands stream). */
    @PostMapping("/internal/commands") public Flag command(@RequestBody FlagCommandEvent cmd){ return svc.applyCommand(cmd); }
}
@RestController
class InternalEventFeed {
    private final FlagEventBus bus; private final ObjectMapper json;
    InternalEventFeed(FlagEventBus b, ObjectMapper j){bus=b;json=j;}
    /** Internal streaming feed: the gateway subscribes here in sandbox profile (Kafka in prod). */
    @GetMapping(value="/internal/config-events", produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(){
        SseEmitter emitter = new SseEmitter(0L);
        var sub = bus.flux().subscribe(ev->{ try{ emitter.send(SseEmitter.event().name("flag-config").id(String.valueOf(ev.configVersion())).data(json.writeValueAsString(ev))); }catch(Exception e){ emitter.completeWithError(e);} },
            emitter::completeWithError, emitter::complete);
        emitter.onCompletion(sub::dispose); emitter.onTimeout(sub::dispose);
        return emitter;
    }
}
@Component @Profile("prod")
class KafkaCommandListener {
    private final FlagService svc; private final ObjectMapper json;
    KafkaCommandListener(FlagService s, ObjectMapper j){svc=s;json=j;}
    @KafkaListener(topics="flag-commands", groupId="control-plane")
    public void onCommand(String payload) throws Exception { svc.applyCommand(json.readValue(payload, FlagCommandEvent.class)); }
}
