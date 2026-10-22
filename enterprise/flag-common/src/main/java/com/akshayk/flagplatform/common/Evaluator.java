package com.akshayk.flagplatform.common;
import com.akshayk.flagplatform.common.Model.*;
import java.util.regex.Pattern;
/** Pure, deterministic evaluation. Order is contractual:
 *  not-found -> kill switch -> targets -> ordered rules -> fallthrough rollout. */
public final class Evaluator {
    public static final String FLAG_NOT_FOUND="FLAG_NOT_FOUND", KILL_SWITCH="KILL_SWITCH",
        TARGET_MATCH="TARGET_MATCH", RULE_MATCH="RULE_MATCH", FALLOUT_ROLLOUT="FALLOUT_ROLLOUT", FALLOUT_OFF="FALLOUT_OFF";
    private Evaluator(){}
    public static EvalResult evaluate(Flag flag, EvalContext ctx, Object defaultValue){
        if(flag==null) return new EvalResult("",null,defaultValue,FLAG_NOT_FOUND,null,null,null);
        int bucket = Bucketing.computeBucket(flag.key(), flag.salt(), ctx.userKey());
        Object offValue = flag.variations().getOrDefault(flag.offVariation(), defaultValue);
        if(!flag.enabled()) return new EvalResult(flag.key(), flag.offVariation(), offValue, KILL_SWITCH, flag.version(), null, bucket);
        for(Target t: flag.targets())
            if(t.values().contains(ctx.userKey()))
                return new EvalResult(flag.key(), t.variation(), flag.variations().getOrDefault(t.variation(), defaultValue), TARGET_MATCH, flag.version(), null, bucket);
        for(Rule r: flag.rules()){
            if(matches(r, ctx) && Bucketing.inRollout(bucket, r.rolloutPercentage()))
                return new EvalResult(flag.key(), r.variation(), flag.variations().getOrDefault(r.variation(), defaultValue), RULE_MATCH, flag.version(), r.id(), bucket);
        }
        if(Bucketing.inRollout(bucket, flag.fallthroughPercentage()))
            return new EvalResult(flag.key(), flag.fallthroughVariation(), flag.variations().getOrDefault(flag.fallthroughVariation(), defaultValue), FALLOUT_ROLLOUT, flag.version(), null, bucket);
        return new EvalResult(flag.key(), flag.offVariation(), offValue, FALLOUT_OFF, flag.version(), null, bucket);
    }
    static boolean matches(Rule r, EvalContext ctx){ for(Clause c: r.clauses()) if(!matches(c,ctx)) return false; return true; }
    static boolean matches(Clause c, EvalContext ctx){
        Object actual = ctx.get(c.attribute()); String op = c.operator();
        if(op.equals("exists")) return actual!=null;
        if(op.equals("not_exists")) return actual==null;
        if(actual==null) return false;
        try{
            switch(op){
                case "equals": return c.values().stream().anyMatch(v->String.valueOf(actual).equals(String.valueOf(v)) || actual.equals(v));
                case "not_equals": return c.values().stream().allMatch(v->!actual.equals(v));
                case "in": return c.values().contains(actual) || c.values().stream().anyMatch(v->String.valueOf(v).equals(String.valueOf(actual)));
                case "not_in": return c.values().stream().noneMatch(v->String.valueOf(v).equals(String.valueOf(actual)));
                case "startsWith": return actual instanceof String s && c.values().stream().anyMatch(v->s.startsWith(String.valueOf(v)));
                case "endsWith": return actual instanceof String s && c.values().stream().anyMatch(v->s.endsWith(String.valueOf(v)));
                case "contains": return String.valueOf(actual).contains(String.valueOf(c.values().isEmpty()?"":c.values().get(0))) && c.values().stream().anyMatch(v->String.valueOf(actual).contains(String.valueOf(v)));
                case "gt": return c.values().stream().anyMatch(v->compare(actual,v)>0);
                case "gte": return c.values().stream().anyMatch(v->compare(actual,v)>=0);
                case "lt": return c.values().stream().anyMatch(v->compare(actual,v)<0);
                case "lte": return c.values().stream().anyMatch(v->compare(actual,v)<=0);
                case "regex": return actual instanceof String s && c.values().stream().anyMatch(v->Pattern.compile(String.valueOf(v)).matcher(s).find());
                default: return false;
            }
        }catch(Exception e){ return false; }
    }
    static int compare(Object a, Object b){
        double da = a instanceof Number n? n.doubleValue(): Double.parseDouble(String.valueOf(a));
        double db = b instanceof Number n? n.doubleValue(): Double.parseDouble(String.valueOf(b));
        return Double.compare(da,db);
    }
}
