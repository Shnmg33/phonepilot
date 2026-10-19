package com.phonepilot.bridge;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Base64;
import android.util.DisplayMetrics;
import android.view.Display;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.util.ArrayDeque;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

final class PhoneActions {
    private final PhoneService service;
    private final int generation;
    private final Handler main = new Handler(Looper.getMainLooper());
    PhoneActions(PhoneService service, int generation) { this.service = service; this.generation = generation; }
    private <T> T onMain(Callable<T> work) throws Exception {
        FutureTask<T> future = new FutureTask<>(() -> {
            if (!service.accepting(generation)) throw new IllegalStateException("手机端已停止桥接，未执行新的操作");
            return work.call();
        });
        main.post(future);
        try { return future.get(8, TimeUnit.SECONDS); }
        finally { future.cancel(false); }
    }
    boolean locked() { return ((KeyguardManager) service.getSystemService(Context.KEYGUARD_SERVICE)).isKeyguardLocked(); }
    boolean interactive() { return ((PowerManager) service.getSystemService(Context.POWER_SERVICE)).isInteractive(); }
    private AccessibilityNodeInfo root() {
        if (locked() || !interactive()) throw new IllegalStateException("手机已锁屏或息屏，请在手机上解锁并保持亮屏");
        AccessibilityNodeInfo root = service.getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("当前界面没有可读取的无障碍窗口");
        if (service.getPackageName().contentEquals(root.getPackageName() == null ? "" : root.getPackageName())) {
            root.recycle(); throw new IllegalStateException("请离开 PhonePilot 配置页，返回桌面或目标应用");
        }
        return root;
    }
    private DisplayMetrics size() {
        DisplayMetrics metrics = new DisplayMetrics();
        ((WindowManager) service.getSystemService(Context.WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(metrics);
        return metrics;
    }
    private String str(CharSequence value) { if (value == null) return ""; String s = value.toString(); return s.substring(0, Math.min(400, s.length())); }
    JSONObject observe(boolean image) throws Exception {
        JSONObject result = onMain(() -> {
            AccessibilityNodeInfo root = root(); DisplayMetrics metrics = size();
            JSONObject data = new JSONObject().put("width", metrics.widthPixels).put("height", metrics.heightPixels)
                .put("package", str(root.getPackageName())).put("warning", "");
            JSONArray nodes = new JSONArray(); ArrayDeque<AccessibilityNodeInfo> pending = new ArrayDeque<>(); pending.add(root);
            int visited = 0;
            try {
                while (!pending.isEmpty() && nodes.length() < 250 && visited++ < 2000) {
                    AccessibilityNodeInfo node = pending.removeFirst();
                    try {
                        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
                        if (node.isVisibleToUser() && !bounds.isEmpty() && (node.isClickable() || node.isScrollable() || node.isFocusable()
                                || node.getText() != null || node.getContentDescription() != null)) {
                            nodes.put(new JSONObject().put("id", nodes.length()).put("text", node.isPassword() ? "[password]" : str(node.getText()))
                                .put("description", node.isPassword() ? "" : str(node.getContentDescription()))
                                .put("resource_id", node.getViewIdResourceName() == null ? "" : node.getViewIdResourceName())
                                .put("class", str(node.getClassName())).put("package", str(node.getPackageName()))
                                .put("bounds", new JSONArray(new int[]{bounds.left, bounds.top, bounds.right, bounds.bottom}))
                                .put("clickable", node.isClickable()).put("scrollable", node.isScrollable()).put("enabled", node.isEnabled()));
                        }
                        for (int i = 0; i < node.getChildCount() && pending.size() < 2000; i++) {
                            AccessibilityNodeInfo child = node.getChild(i); if (child != null) pending.add(child);
                        }
                    } finally { node.recycle(); }
                }
            } finally { while (!pending.isEmpty()) pending.remove().recycle(); }
            if (nodes.length() == 250 || visited >= 2000) data.put("warning", "界面节点已截断，必要时滚动后再观察");
            return data.put("nodes", nodes);
        });
        if (image) {
            JSONObject screenshot = screenshot();
            if (screenshot.getInt("width") != result.getInt("width") || screenshot.getInt("height") != result.getInt("height"))
                throw new IllegalStateException("观察期间屏幕方向发生变化，请重新观察");
            result.put("screenshot", screenshot.getString("screenshot"));
        }
        return result;
    }
    JSONObject screenshot() throws Exception {
        CompletableFuture<JSONObject> future = new CompletableFuture<>();
        onMain(() -> {
            root().recycle();
            service.takeScreenshot(Display.DEFAULT_DISPLAY, service.getScreenshotExecutor(), new AccessibilityService.TakeScreenshotCallback() {
                @Override public void onSuccess(AccessibilityService.ScreenshotResult result) {
                    try (HardwareBuffer buffer = result.getHardwareBuffer()) {
                        Bitmap hardware = Bitmap.wrapHardwareBuffer(buffer, result.getColorSpace());
                        if (hardware == null) throw new IllegalStateException("系统未提供截图位图");
                        Bitmap bitmap;
                        try { bitmap = hardware.copy(Bitmap.Config.ARGB_8888, false); } finally { hardware.recycle(); }
                        if (bitmap == null) throw new IllegalStateException("截图转换失败");
                        try {
                            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                            if (!bitmap.compress(Bitmap.CompressFormat.PNG, 100, bytes)) throw new IllegalStateException("截图编码失败");
                            future.complete(new JSONObject().put("width", bitmap.getWidth()).put("height", bitmap.getHeight())
                                .put("screenshot", Base64.encodeToString(bytes.toByteArray(), Base64.NO_WRAP)));
                        } finally { bitmap.recycle(); }
                    } catch (Exception error) { future.completeExceptionally(error); }
                }
                @Override public void onFailure(int errorCode) {
                    future.completeExceptionally(new IllegalStateException("系统拒绝截图（错误码 " + errorCode + "）；安全窗口、频率限制或系统策略可能不支持"));
                }
            });
            return null;
        });
        return future.get(10, TimeUnit.SECONDS);
    }
    JSONObject action(JSONObject action) throws Exception {
        String type = action.getString("type");
        if (type.equals("wait")) {
            onMain(() -> { root().recycle(); return null; });
            double seconds = action.optDouble("seconds", 1);
            if (!Double.isFinite(seconds) || seconds < .2 || seconds > 5) throw new IllegalArgumentException("等待时长无效");
            Thread.sleep((long) (seconds * 1000));
        } else if (type.equals("tap") || type.equals("swipe")) {
            CompletableFuture<Boolean> complete = new CompletableFuture<>();
            onMain(() -> {
                root().recycle(); DisplayMetrics metrics = size();
                int x = action.getInt("x"), y = action.getInt("y");
                int x2 = type.equals("swipe") ? action.getInt("x2") : x, y2 = type.equals("swipe") ? action.getInt("y2") : y;
                if (x < 0 || y < 0 || x >= metrics.widthPixels || y >= metrics.heightPixels
                        || x2 < 0 || y2 < 0 || x2 >= metrics.widthPixels || y2 >= metrics.heightPixels)
                    throw new IllegalArgumentException("手势坐标超出屏幕");
                long duration = type.equals("swipe") ? action.optInt("duration", 400) : 80;
                if (duration < 50 || duration > 3000) throw new IllegalArgumentException("手势时长无效");
                Path path = new Path(); path.moveTo(x, y); if (type.equals("swipe")) path.lineTo(x2, y2);
                GestureDescription gesture = new GestureDescription.Builder().addStroke(new GestureDescription.StrokeDescription(path, 0, duration)).build();
                boolean submitted = service.dispatchGesture(gesture, new AccessibilityService.GestureResultCallback() {
                    @Override public void onCompleted(GestureDescription gesture) { complete.complete(true); }
                    @Override public void onCancelled(GestureDescription gesture) { complete.complete(false); }
                }, main);
                if (!submitted) complete.complete(false);
                return null;
            });
            if (!complete.get(8, TimeUnit.SECONDS)) throw new IllegalStateException("系统取消或拒绝了手势");
        } else {
            onMain(() -> {
                AccessibilityNodeInfo root = root();
                try {
                    if (type.equals("text")) {
                        String text = action.getString("text"); if (text.length() > 2000) throw new IllegalArgumentException("文本过长");
                        AccessibilityNodeInfo field = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
                        if (field == null) throw new IllegalStateException("没有聚焦的输入框，请先点击输入框");
                        try { setText(field, text); } finally { field.recycle(); }
                    } else if (type.equals("key")) {
                        pressKey(root, action.getString("key"));
                    } else if (type.equals("launch")) {
                        String pkg = action.getString("package");
                        if (!pkg.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)+") || pkg.equals(service.getPackageName()))
                            throw new IllegalArgumentException("不支持此应用包名");
                        Intent launch = service.getPackageManager().getLaunchIntentForPackage(pkg);
                        if (launch == null) throw new IllegalArgumentException("应用未安装、不可见或没有启动入口");
                        launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK); service.startActivity(launch);
                    } else throw new IllegalArgumentException("未支持的动作类型");
                } finally { root.recycle(); }
                return null;
            });
        }
        return new JSONObject().put("ok", true);
    }
    private void setText(AccessibilityNodeInfo field, String text) {
        if (!field.isEditable() || !field.isEnabled()) throw new IllegalStateException("当前控件不可编辑");
        Bundle args = new Bundle(); args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        if (!field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)) throw new IllegalStateException("应用不支持无障碍文字输入");
    }
    private void pressKey(AccessibilityNodeInfo root, String key) {
        int global = switch (key) {
            case "HOME" -> AccessibilityService.GLOBAL_ACTION_HOME;
            case "BACK" -> AccessibilityService.GLOBAL_ACTION_BACK;
            case "APP_SWITCH" -> AccessibilityService.GLOBAL_ACTION_RECENTS;
            default -> 0;
        };
        if (global != 0) { if (!service.performGlobalAction(global)) throw new IllegalStateException("全局按键执行失败"); return; }
        AccessibilityNodeInfo field = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (field == null) throw new IllegalStateException("没有聚焦的输入控件");
        try {
            if (key.equals("ENTER")) {
                if (!field.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.getId()))
                    throw new IllegalStateException("应用不支持输入法确认动作，请点击界面中的确认按钮");
            } else if (key.equals("TAB")) {
                AccessibilityNodeInfo next = field.focusSearch(android.view.View.FOCUS_FORWARD);
                if (next == null) throw new IllegalStateException("没有下一个焦点");
                try { if (!next.performAction(AccessibilityNodeInfo.ACTION_FOCUS)) throw new IllegalStateException("无法移动焦点"); }
                finally { next.recycle(); }
            } else if (key.equals("DEL")) {
                if (field.isPassword()) throw new IllegalStateException("不读取密码字段进行删除，请使用输入框提供的操作");
                String text = field.getText() == null ? "" : field.getText().toString();
                int start = field.getTextSelectionStart(), end = field.getTextSelectionEnd();
                if (start < 0 || end < 0 || start > text.length() || end > text.length()) throw new IllegalStateException("输入框不提供光标位置");
                int from = Math.min(start, end), to = Math.max(start, end);
                if (from == to && from > 0) from = text.offsetByCodePoints(from, -1);
                setText(field, text.substring(0, from) + text.substring(to));
                Bundle selection = new Bundle(); selection.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_START_INT, from);
                selection.putInt(AccessibilityNodeInfo.ACTION_ARGUMENT_SELECTION_END_INT, from); field.performAction(AccessibilityNodeInfo.ACTION_SET_SELECTION, selection);
            } else throw new IllegalArgumentException("不支持此按键");
        } finally { field.recycle(); }
    }
}
