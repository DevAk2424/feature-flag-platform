package com.akshayk.flagplatform.gateway;
import com.akshayk.flagplatform.common.Model.*;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux; import reactor.core.publisher.Sinks;
import java.util.*; import java.util.concurrent.atomic.*;
/** Last-known-good snapshot store. If the control plane / broker goes down this
 *  keeps serving the last snapshot and marks it stale instead of failing clients. */
@Component
public class ConfigStore {
    public record Snapshot(long configVersion, List<Flag> flags, boolean stale, long updatedAtEpochMs){
        public Snapshot{ flags = flags==null?List.of():List.copyOf(flags); }
    }
    private final AtomicReference<Snapshot> snapshot = new AtomicReference<>(new Snapshot(0, List.of(), true, 0));
    private final AtomicBoolean sourceConnected = new AtomicBoolean(false);
    private final Sinks.Many<FlagConfigEvent> deltas = Sinks.many().multicast().onBackpressureBuffer(1024,false);
    public Snapshot snapshot(){ var s=snapshot.get(); return new Snapshot(s.configVersion(), s.flags(), !sourceConnected.get(), s.updatedAtEpochMs()); }
    public void loadSnapshot(long version, List<Flag> flags){ snapshot.set(new Snapshot(version, flags, false, System.currentTimeMillis())); sourceConnected.set(true); }
    public void applyEvent(FlagConfigEvent ev){
        snapshot.updateAndGet(s->{
            Map<String,Flag> byKey = new LinkedHashMap<>();
            for(Flag f: s.flags()) byKey.put(f.key(), f);
            if(ev.flag()!=null) byKey.put(ev.flagKey(), ev.flag());
            return new Snapshot(ev.configVersion(), List.copyOf(byKey.values()), false, System.currentTimeMillis());
        });
        sourceConnected.set(true); deltas.tryEmitNext(ev);
    }
    public Flux<FlagConfigEvent> deltas(){ return deltas.asFlux(); }
    public void markDisconnected(){ sourceConnected.set(false); }
}
