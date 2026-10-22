package com.akshayk.flagplatform.controlplane;
import com.akshayk.flagplatform.common.Model.Flag;
import org.springframework.boot.CommandLineRunner; import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;
@Configuration class Seed {
    @Bean CommandLineRunner seedFlags(FlagService svc){
        return args->{ if(svc.find("checkout-redesign").isEmpty()) svc.create(Flag.simple("checkout-redesign",10), "seed");
                       if(svc.find("legacy-search").isEmpty()){ svc.create(Flag.simple("legacy-search",100), "seed"); svc.setEnabled("legacy-search", false, "seed"); } };
    }
}
