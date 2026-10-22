package com.akshayk.flagplatform.common;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
/** Stable SHA-256 bucketing, identical algorithm to the v1 Python engine:
 *  bucket = int(sha256("flagKey.salt.userKey")[0..8 hex],16) % 10000. */
public final class Bucketing {
    public static final int BUCKET_COUNT = 10_000;
    private Bucketing(){}
    public static int computeBucket(String flagKey, String salt, String userKey){
        try{
            String material = flagKey + "." + salt + "." + userKey;
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder();
            for(byte b: digest) hex.append(String.format("%02x", b));
            return (int)(Long.parseLong(hex.substring(0,8),16) % BUCKET_COUNT);
        }catch(Exception e){ throw new IllegalStateException(e); }
    }
    /** Monotonic: raising percentage never drops an already-included user. */
    public static boolean inRollout(int bucket, double percentage){
        if(percentage<=0) return false; if(percentage>=100) return true;
        return bucket < (int)(percentage*100);
    }
}
