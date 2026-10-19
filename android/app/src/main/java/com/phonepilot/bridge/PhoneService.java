package com.phonepilot.bridge;

import android.accessibilityservice.AccessibilityService;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.os.PowerManager;
import android.view.accessibility.AccessibilityEvent;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class PhoneService extends AccessibilityService {
    public static volatile PhoneService instance;
    public static volatile String status = "未启动";
    private Config config;
    private Thread worker;
    private volatile int generation = 0;
    private volatile HttpURLConnection connection;
    private ExecutorService screenshots;
    private static final int NOTIFICATION_ID = 401;
    ExecutorService getScreenshotExecutor() { return screenshots; }
    boolean accepting(int tag) { return instance == this && tag == generation && config.enabled(); }

    @Override protected void onServiceConnected() {
        instance = this; config = new Config(this); screenshots = Executors.newSingleThreadExecutor();
        getSystemService(NotificationManager.class).createNotificationChannel(new NotificationChannel("bridge", "PhonePilot 连接状态", NotificationManager.IMPORTANCE_LOW));
        status = "无障碍已开启，等待启动";
        if (config.enabled() && config.ready()) startBridge();
    }
    public synchronized boolean startBridge() {
        if (worker != null && worker.isAlive()) { config.enabled(false); status = "旧连接正在停止，请稍后再次启动"; return false; }
        if (!config.ready()) { config.enabled(false); status = "请先配置服务器和令牌"; return false; }
        int tag = ++generation;
        worker = new Thread(() -> runBridge(tag), "phonepilot-bridge"); worker.start();
        notification("正在连接服务器");
        return true;
    }
    public synchronized void stopBridge() {
        config.enabled(false); generation++;
        if (worker != null) worker.interrupt();
        HttpURLConnection current = connection; if (current != null) current.disconnect();
        status = "已停止；已发出的单次手势可能仍会完成";
        getSystemService(NotificationManager.class).cancel(NOTIFICATION_ID);
    }
    private void notification(String message) {
        PendingIntent open = PendingIntent.getActivity(this, 1, new Intent(this, MainActivity.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        PendingIntent stop = PendingIntent.getBroadcast(this, 2, new Intent(this, StopReceiver.class), PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification item = new Notification.Builder(this, "bridge").setContentTitle("PhonePilot 手机桥接")
            .setContentText(message).setSmallIcon(com.phonepilot.bridge.R.drawable.ic_bridge).setOngoing(true)
            .setContentIntent(open).addAction(new Notification.Action.Builder(null, "停止桥接", stop).build()).build();
        try { getSystemService(NotificationManager.class).notify(NOTIFICATION_ID, item); } catch (SecurityException ignored) { }
    }
    private JSONObject post(String server, String token, String path, JSONObject body, int tag) throws Exception {
        if (!accepting(tag)) throw new InterruptedException();
        HttpURLConnection conn = (HttpURLConnection) new URL(server + path).openConnection();
        connection = conn;
        try {
            if (!accepting(tag)) throw new InterruptedException();
            conn.setRequestMethod("POST"); conn.setInstanceFollowRedirects(false);
            conn.setConnectTimeout(8000); conn.setReadTimeout(25000); conn.setDoOutput(true);
            conn.setRequestProperty("Authorization", "Bearer " + token); conn.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8); conn.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream out = conn.getOutputStream()) { out.write(bytes); }
            int code = conn.getResponseCode();
            if (code != 200) throw new IllegalStateException("服务器返回 HTTP " + code + "，请检查地址、令牌和服务器版本");
            try (InputStream in = conn.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192]; int n;
                while ((n = in.read(buffer)) != -1) { out.write(buffer, 0, n); if (out.size() > 1024 * 1024) throw new IllegalStateException("服务器响应过大"); }
                return new JSONObject(out.toString(StandardCharsets.UTF_8.name()));
            }
        } finally { conn.disconnect(); if (connection == conn) connection = null; }
    }
    private JSONObject device(PhoneActions actions, String serial) throws Exception {
        JSONObject capabilities = new JSONObject().put("adapter", "android-accessibility")
            .put("text_semantics", "text replaces the entire focused editable field; use full desired text; Unicode supported")
            .put("keys", new JSONArray(new String[]{"HOME","BACK","APP_SWITCH","ENTER","TAB","DEL"}))
            .put("screenshots", "Android accessibility screenshot, secure windows may reject")
            .put("limitations", "Cannot unlock the device; ENTER/TAB depend on app support; do not send ADB commands");
        return new JSONObject().put("serial", serial).put("state", "device").put("name", Build.MANUFACTURER + " " + Build.MODEL)
            .put("transport", "手机原生 · HTTPS").put("locked", actions.locked()).put("interactive", actions.interactive())
            .put("android_version", Build.VERSION.RELEASE).put("capabilities", capabilities);
    }
    private String errorMessage(Exception error) {
        Throwable cause = error; while (cause.getCause() != null) cause = cause.getCause();
        if (cause instanceof IllegalArgumentException || cause instanceof IllegalStateException) return cause.getMessage() == null ? "手机操作失败" : cause.getMessage();
        if (cause instanceof java.util.concurrent.TimeoutException) return "手机操作超时；结果未确认，请检查手机，勿自动重试";
        return "手机操作或连接失败（" + cause.getClass().getSimpleName() + "），请检查手机与网络";
    }
    private void runBridge(int tag) {
        try {
            String server = config.server(), token = config.token(), bridge = config.bridgeId(), serial = config.serial();
            PhoneActions actions = new PhoneActions(this, tag);
            while (accepting(tag)) {
                try {
                    JSONObject poll = new JSONObject().put("bridge_id", bridge).put("devices", new JSONArray().put(device(actions, serial))).put("wait_seconds", 15);
                    JSONObject response = post(server, token, "/api/bridge/poll", poll, tag);
                    if (!accepting(tag)) break;
                    status = actions.locked() || !actions.interactive() ? "已连接，等待手机亮屏解锁" : "已连接，等待服务器任务";
                    notification(status);
                    JSONObject command = response.optJSONObject("command");
                    if (command != null) {
                        JSONObject output = new JSONObject().put("bridge_id", bridge).put("command_id", command.getString("id"));
                        PowerManager.WakeLock wake = ((PowerManager) getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "phonepilot:command");
                        try {
                            if (!serial.equals(command.getString("serial"))) throw new IllegalArgumentException("命令设备标识不匹配");
                            if (System.currentTimeMillis() / 1000.0 > command.getDouble("expires")) throw new IllegalStateException("命令已过期，未执行");
                            wake.acquire(30000); status = "正在执行服务器操作";
                            String op = command.getString("operation"); JSONObject payload = command.optJSONObject("payload");
                            JSONObject result = switch (op) {
                                case "observe" -> actions.observe(payload != null && payload.optBoolean("include_screenshot", false));
                                case "screenshot" -> actions.screenshot();
                                case "action" -> actions.action(payload == null ? new JSONObject() : payload);
                                default -> throw new IllegalArgumentException("未知操作类型");
                            };
                            output.put("result", result);
                        } catch (Exception error) { output.put("error", errorMessage(error)); }
                        finally { if (wake.isHeld()) wake.release(); }
                        boolean sent = false;
                        // Only retry delivery. Never execute the command again.
                        for (int attempt = 0; attempt < 3 && accepting(tag); attempt++) {
                            try { post(server, token, "/api/bridge/result", output, tag); sent = true; break; }
                            catch (Exception error) { if (!accepting(tag)) break; Thread.sleep(1000L * (attempt + 1)); }
                        }
                        if (!sent && accepting(tag)) { status = "结果未回传，请检查服务器待确认任务；未重复执行操作"; Thread.sleep(5000); }
                    }
                } catch (InterruptedException interrupted) { break; }
                catch (Exception error) { if (!accepting(tag)) break; status = errorMessage(error); notification(status); Thread.sleep(5000); }
            }
        } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        catch (Exception error) { if (accepting(tag)) { status = errorMessage(error); config.enabled(false); notification(status); } }
    }
    @Override public void onAccessibilityEvent(AccessibilityEvent event) { /* Read UI only when the server requests observation. */ }
    @Override public void onInterrupt() { if (config != null) stopBridge(); }
    @Override public void onDestroy() {
        // Keep the user's opt-in across system rebinding, but terminate all work in this service instance.
        generation++;
        if (worker != null) worker.interrupt();
        HttpURLConnection current = connection; if (current != null) current.disconnect();
        if (screenshots != null) screenshots.shutdownNow();
        if (instance == this) instance = null;
        status = "无障碍服务已断开，请检查系统后台设置";
        getSystemService(NotificationManager.class).cancel(NOTIFICATION_ID);
        super.onDestroy();
    }
}
