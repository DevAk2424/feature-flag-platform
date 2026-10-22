package com.akshayk.flagplatform.common;
import com.akshayk.flagplatform.common.Model.*;
import org.junit.jupiter.api.Test;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
class EvaluatorTest {
    @Test void bucketIsStableAndInRange(){
        int b1=Bucketing.computeBucket("checkout","checkout","user-42");
        assertEquals(b1, Bucketing.computeBucket("checkout","checkout","user-42"));
        assertTrue(b1>=0 && b1<10000);
    }
    @Test void rolloutIsMonotonic(){
        Flag f10=Flag.simple("f",10), f25=Flag.simple("f",25);
        for(int i=0;i<500;i++){ String u="user-"+i;
            var r10=Evaluator.evaluate(f10,EvalContext.of(u),false);
            if(r10.reason().equals(Evaluator.FALLOUT_ROLLOUT))
                assertEquals(Evaluator.FALLOUT_ROLLOUT, Evaluator.evaluate(f25,EvalContext.of(u),false).reason());
        }
    }
    @Test void rolloutEdges(){ 
        assertEquals(Evaluator.FALLOUT_OFF, Evaluator.evaluate(Flag.simple("f",0),EvalContext.of("u1"),false).reason());
        assertEquals(Evaluator.FALLOUT_ROLLOUT, Evaluator.evaluate(Flag.simple("f",100),EvalContext.of("u1"),false).reason());
    }
    @Test void killSwitchBeatsTargets(){
        Flag f=new Flag("f",false,1,Map.of("on",true,"off",false),"off","on",100,
            List.of(),List.of(new Target(List.of("vip"),"on")),"f","","prod",List.of());
        assertEquals(Evaluator.KILL_SWITCH, Evaluator.evaluate(f,EvalContext.of("vip"),false).reason());
    }
    @Test void targetMatch(){
        Flag f=new Flag("f",true,1,Map.of("on",true,"off",false),"off","on",0,
            List.of(),List.of(new Target(List.of("vip"),"on")),"f","","prod",List.of());
        assertEquals(Evaluator.TARGET_MATCH, Evaluator.evaluate(f,EvalContext.of("vip"),false).reason());
    }
    @Test void ruleOperatorsAndOrdering(){
        Rule beta=new Rule("beta","on",List.of(new Clause("plan", "equals", List.of("beta"))),100);
        Rule paid=new Rule("paid","on",List.of(new Clause("tier","in",List.of("pro","team")), new Clause("seats","gte",List.of(5))),100);
        Flag f=new Flag("f",true,1,Map.of("on",true,"off",false),"off","on",0,List.of(beta,paid),List.of(),"f","","prod",List.of());
        assertEquals("beta", Evaluator.evaluate(f,new EvalContext("u",Map.of("plan","beta")),false).ruleId());
        assertEquals("paid", Evaluator.evaluate(f,new EvalContext("u",Map.of("tier","pro","seats",10)),false).ruleId());
        assertEquals(Evaluator.FALLOUT_OFF, Evaluator.evaluate(f,new EvalContext("u",Map.of("tier","free","seats",1)),false).reason());
    }
    @Test void notFound(){ assertEquals(Evaluator.FLAG_NOT_FOUND, Evaluator.evaluate(null,EvalContext.of("u"),false).reason()); }
    @Test void distributionRoughlyMatchesPercentage(){
        Flag f=Flag.simple("dist",50); int in=0,n=4000;
        for(int i=0;i<n;i++) if(Evaluator.evaluate(f,EvalContext.of("user-"+i),false).reason().equals(Evaluator.FALLOUT_ROLLOUT)) in++;
        double pct=in*100.0/n; assertTrue(pct>44 && pct<56, "got "+pct);
    }
}
