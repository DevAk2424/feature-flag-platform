package com.akshayk.flagplatform.common;
import java.util.*;
/** Domain model shared by every microservice (single source of truth). */
public final class Model {
    private Model(){}
    public record Clause(String attribute, String operator, List<Object> values){
        public Clause{ values = values==null?List.of():List.copyOf(values); }
    }
    public record Rule(String id, String variation, List<Clause> clauses, double rolloutPercentage){
        public Rule{ clauses = clauses==null?List.of():List.copyOf(clauses); }
    }
    public record Target(List<String> values, String variation){
        public Target{ values = values==null?List.of():List.copyOf(values); }
    }
    public record Flag(String key, boolean enabled, long version, Map<String,Object> variations,
                       String offVariation, String fallthroughVariation, double fallthroughPercentage,
                       List<Rule> rules, List<Target> targets, String salt, String description,
                       String environment, List<String> tags){
        public Flag{
            variations = variations==null?Map.of("on",true,"off",false):Map.copyOf(variations);
            offVariation = offVariation==null?"off":offVariation;
            fallthroughVariation = fallthroughVariation==null?"on":fallthroughVariation;
            rules = rules==null?List.of():List.copyOf(rules);
            targets = targets==null?List.of():List.copyOf(targets);
            salt = (salt==null||salt.isBlank())?key:salt;
            description = description==null?"":description;
            environment = environment==null?"prod":environment;
            tags = tags==null?List.of():List.copyOf(tags);
        }
        public Flag withVersion(long v){ return new Flag(key,enabled,v,variations,offVariation,fallthroughVariation,fallthroughPercentage,rules,targets,salt,description,environment,tags); }
        public Flag withRollout(double pct){ return new Flag(key,enabled,version,variations,offVariation,fallthroughVariation,pct,rules,targets,salt,description,environment,tags); }
        public Flag withEnabled(boolean e){ return new Flag(key,e,version,variations,offVariation,fallthroughVariation,fallthroughPercentage,rules,targets,salt,description,environment,tags); }
        public static Flag simple(String key, double rolloutPct){
            return new Flag(key,true,1,Map.of("on",true,"off",false),"off","on",rolloutPct,List.of(),List.of(),key,"","prod",List.of());
        }
    }
    public record EvalContext(String userKey, Map<String,Object> attributes){
        public EvalContext{ attributes = attributes==null?Map.of():Map.copyOf(attributes); }
        public Object get(String attribute){
            if(attribute.equals("key")||attribute.equals("user_key")||attribute.equals("userKey")) return userKey;
            return attributes.get(attribute);
        }
        public static EvalContext of(String userKey){ return new EvalContext(userKey, Map.of()); }
    }
    public record EvalResult(String flagKey, String variation, Object value, String reason,
                             Long flagVersion, String ruleId, Integer bucket){}
    /** Event streamed on flag-config-events whenever config changes. */
    public record FlagConfigEvent(String eventId, String type, long configVersion, String actor,
                                  long timestampEpochMs, Flag flag, String flagKey){}
    /** Command event sent by the AI risk service (after human approval) to the control plane. */
    public record FlagCommandEvent(String commandId, String type, String flagKey, Double targetRolloutPercentage,
                                   Boolean targetEnabled, String actor, String proposalId, long timestampEpochMs){}
}
