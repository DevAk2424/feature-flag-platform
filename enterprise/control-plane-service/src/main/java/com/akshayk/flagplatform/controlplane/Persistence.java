package com.akshayk.flagplatform.controlplane;
import jakarta.persistence.*;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;
@Entity @Table(name="flags_tbl") class FlagEntity {
    @Id @Column(name="flag_key") String key; String env; long version; @Column(length=20000) String payload;
    FlagEntity(){} FlagEntity(String k,String e,long v,String p){key=k;env=e;version=v;payload=p;}
}
@Entity class HistoryEntity { @Id @GeneratedValue(strategy=GenerationType.IDENTITY) Long id;
    String flagKey; long version; @Column(length=20000) String payload; long ts;
    HistoryEntity(){} HistoryEntity(String k,long v,String p,long t){flagKey=k;version=v;payload=p;ts=t;} }
@Entity class AuditEntity { @Id @GeneratedValue(strategy=GenerationType.IDENTITY) Long id;
    String flagKey; String actor; String action; @Column(length=20000) String oldValue; @Column(length=20000) String newValue; Long version; long ts;
    AuditEntity(){} AuditEntity(String k,String a,String act,String o,String n,Long v,long t){flagKey=k;actor=a;action=act;oldValue=o;newValue=n;version=v;ts=t;} }
interface FlagRepo extends JpaRepository<FlagEntity,String>{ List<FlagEntity> findByEnv(String env); }
interface HistoryRepo extends JpaRepository<HistoryEntity,Long>{ List<HistoryEntity> findByFlagKeyOrderByVersionAsc(String k); }
interface AuditRepo extends JpaRepository<AuditEntity,Long>{ List<AuditEntity> findAllByOrderByIdAsc(); }
