package com.phonepilot.bridge;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.UUID;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class Config {
    private final SharedPreferences prefs;
    Config(Context context) { prefs = context.getSharedPreferences("phonepilot", Context.MODE_PRIVATE); }
    String server() { return prefs.getString("server", ""); }
    String bridgeId() { return prefs.getString("bridge", "iqoo"); }
    String serial() {
        String id = prefs.getString("serial", "");
        if (id.isEmpty()) { id = "android-" + UUID.randomUUID().toString().substring(0, 12); prefs.edit().putString("serial", id).commit(); }
        return id;
    }
    boolean enabled() { return prefs.getBoolean("enabled", false); }
    void enabled(boolean value) { prefs.edit().putBoolean("enabled", value).commit(); }
    boolean ready() { return !server().isEmpty() && !prefs.getString("token", "").isEmpty(); }
    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias("phonepilot-token")) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder("phonepilot-token", KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey("phonepilot-token", null);
    }
    String token() throws Exception {
        String value = prefs.getString("token", "");
        if (value.isEmpty()) return "";
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)));
        return new String(cipher.doFinal(Base64.decode(value, Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }
    void save(String server, String bridge, String token) throws Exception {
        server = server.trim().replaceAll("/+$", "");
        URI uri = URI.create(server);
        if (!"https".equalsIgnoreCase(uri.getScheme()) || uri.getHost() == null || uri.getRawUserInfo() != null
                || uri.getRawQuery() != null || uri.getRawFragment() != null || !(uri.getPath().isEmpty() || uri.getPath().equals("/")))
            throw new IllegalArgumentException("请输入 HTTPS 域名地址，不含路径、密钥或查询参数");
        if (!bridge.matches("[a-zA-Z0-9_-]{1,64}")) throw new IllegalArgumentException("桥接 ID 只允许字母、数字、下划线与连字符");
        if (token.length() < 24) throw new IllegalArgumentException("BRIDGE_TOKEN 至少需要 24 个字符");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key());
        prefs.edit().putString("server", server).putString("bridge", bridge)
            .putString("token", Base64.encodeToString(cipher.doFinal(token.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP))
            .putString("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP)).commit();
    }
}
