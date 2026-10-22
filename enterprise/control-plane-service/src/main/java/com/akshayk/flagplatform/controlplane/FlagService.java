package com.akshayk.flagplatform.controlplane;
import com.akshayk.flagplatform.common.Model.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*; import java.util.concurrent.atomic.AtomicLong;
@Service
public class FlagService {
    private final FlagRepo flags; private final HistoryRepo history; private final AuditRepo audit;
    private final ObjectMapper json; private final FlagEventPublisher publisher;
    private final AtomicLong configVersion = new AtomicLong(0);
    public FlagService(FlagRepo f, HistoryRepo h, AuditRepo a, ObjectMapper j, FlagEventPublisher p){flags=f;history=h;audit=a;json=j;publisher=p;}
    String write(Object o){ try{return json.writeValueAsString(o);}catch(Exception e){throw new IllegalStateException(e);} }
    Flag read(String s){ try{return json.readValue(s, Flag.class);}catch(Exception e){throw new IllegalStateException(e);} }
    public long configVersion(){ return configVersion.get(); }
    @Transactional public synchronized Flag create(Flag in, String actor){
        if(flags.existsById(in.key())) throw new IllegalArgumentException("flag already exists: "+in.key());
        return commit(in.withVersion(1), actor, "CREATE", null);
    }
    @Transactional public synchronized Flag update(String key, Flag in, String actor){
        Flag old = get(key); Flag next = new Flag(key, in.enabled(), old.version()+1, in.variations(), in.offVariation(), in.fallthroughVariation(), in.fallthroughPercentage(), in.rules(), in.targets(), in.salt(), in.description(), in.environment(), in.tags());
        return commit(next, actor, "UPDATE", old);
    }
    @Transactional public synchronized Flag patchRollout(String key, double pct, String actor){
        if(pct<0||pct>100) throw new IllegalArgumentException("percentage must be 0..100");
        Flag old=get(key); return commit(old.withRollout(pct).withVersion(old.version()+1), actor, "ROLLOUT", old);
    }
    @Transactional public synchronized Flag setEnabled(String key, boolean enabled, String actor){
        Flag old=get(key); return commit(old.withEnabled(enabled).withVersion(old.version()+1), actor, enabled?"ENABLE":"KILL_SWITCH", old);
    }
    @Transactional public synchronized Flag rollback(String key, long version, String actor){
        Flag old=get(key);
        HistoryEntity h = history.findByFlagKeyOrderByVersionAsc(key).stream().filter(x->x.version==version).findFirst()
            .orElseThrow(()->new NoSuchElementException("version not found: "+version));
        Flag restored = read(h.payload).withVersion(old.version()+1); // forward version: rollback never rewinds version numbers
        return commit(restored, actor, "ROLLBACK_TO_"+version, old);
    }
    private Flag commit(Flag next, String actor, String action, Flag old){
        flags.save(new FlagEntity(next.key(), next.environment(), next.version(), write(next)));
        history.save(new HistoryEntity(next.key(), next.version(), write(next), System.currentTimeMillis()));
        audit.save(new AuditEntity(next.key(), actor==null?"system":actor, action, old==null?null:write(old), write(next), next.version(), System.currentTimeMillis()));
        long cv = configVersion.incrementAndGet();
        publisher.publish(new FlagConfigEvent(UUID.randomUUID().toString(), action, cv, actor==null?"system":actor, System.currentTimeMillis(), next, next.key()));
        return next;
    }
    public Flag get(String key){ return flags.findById(key).map(e->read(e.payload)).orElseThrow(()->new NoSuchElementException("flag not found: "+key)); }
    public Optional<Flag> find(String key){ return flags.findById(key).map(e->read(e.payload)); }
    public List<Flag> list(String env){ return (env==null? flags.findAll(): flags.findByEnv(env)).stream().map(e->read(e.payload)).sorted(Comparator.comparing(Flag::key)).toList(); }
    public List<AuditEntity> audit(){ return audit.findAllByOrderByIdAsc(); }
    public List<HistoryEntity> history(String key){ return history.findByFlagKeyOrderByVersionAsc(key); }
    @Transactional public synchronized Flag applyCommand(FlagCommandEvent cmd){
        String actor = "risk-agent-approved-by:"+cmd.actor()+" proposal:"+cmd.proposalId();
        if(cmd.targetRolloutPercentage()!=null) return patchRollout(cmd.flagKey(), cmd.targetRolloutPercentage(), actor);
        if(cmd.targetEnabled()!=null) return setEnabled(cmd.flagKey(), cmd.targetEnabled(), actor);
        throw new IllegalArgumentException("command has no target change");
    }
}
