package com.phonepilot.bridge;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.View;
import android.view.WindowManager;
import android.view.WindowInsets;
import android.widget.*;

public class MainActivity extends Activity {
    private Config config;
    private EditText server, bridge, token;
    private TextView status;
    private CheckBox consent;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable update = new Runnable() { public void run() {
        status.setText("运行状态：" + PhoneService.status + "\n无障碍服务：" + (PhoneService.instance == null ? "未开启" : "已开启")
            + "\n手机端只执行与回传，AI 与技能库仍在云端。");
        handler.postDelayed(this, 1500);
    }};
    private int dp(int value) { return Math.round(value * getResources().getDisplayMetrics().density); }
    private TextView text(LinearLayout parent, String value, int size) {
        TextView v = new TextView(this); v.setText(value); v.setTextSize(size); v.setTextColor(Color.rgb(32, 59, 50));
        v.setPadding(0, dp(10), 0, dp(10)); parent.addView(v); return v;
    }
    private EditText input(LinearLayout parent, String label, String value, int type) {
        text(parent, label, 13); EditText v = new EditText(this); v.setSingleLine(true); v.setText(value); v.setInputType(type);
        v.setTextSize(14); parent.addView(v); return v;
    }
    private void button(LinearLayout parent, String label, View.OnClickListener listener) {
        Button v = new Button(this); v.setText(label); v.setAllCaps(false); v.setOnClickListener(listener); parent.addView(v);
    }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved); config = new Config(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        ScrollView scroll = new ScrollView(this); LinearLayout page = new LinearLayout(this); page.setOrientation(LinearLayout.VERTICAL);
        page.setPadding(dp(24), dp(24), dp(24), dp(30)); page.setBackgroundColor(Color.rgb(245, 247, 241)); scroll.addView(page); setContentView(scroll);
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
            view.setPadding(dp(24) + bars.left, dp(24) + bars.top, dp(24) + bars.right, dp(30) + bars.bottom);
            return insets;
        });
        text(page, "PhonePilot · 手机桥接", 25);
        text(page, "手机直接连接服务器，不需要常开电脑。适用于 Android 11 及以上。", 14);
        server = input(page, "服务器地址（HTTPS）", config.server(), InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        server.setHint("https://phone.example.com");
        bridge = input(page, "桥接 ID（保持不变，供任务识别设备）", config.bridgeId(), InputType.TYPE_CLASS_TEXT);
        token = input(page, "BRIDGE_TOKEN（已保存时可留空）", "", InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        token.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        consent = new CheckBox(this); consent.setText("我了解：启动后，应用可读取屏幕文字、按需截图、点击滑动与输入，并把这些信息发送到我配置的服务器。可随时停止。");
        consent.setChecked(config.enabled()); page.addView(consent);
        button(page, "1. 打开无障碍设置", v -> startActivity(new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        button(page, "2. 保存配置并启动桥接", v -> {
            try {
                if (!consent.isChecked()) throw new IllegalArgumentException("请先阅读并勾选上方说明");
                if (PhoneService.instance == null) throw new IllegalArgumentException("请先在系统无障碍设置中启用 PhonePilot");
                if (config.enabled()) throw new IllegalArgumentException("修改连接配置前，请先停止桥接");
                String secret = token.getText().toString().trim(); if (secret.isEmpty()) secret = config.token();
                config.save(server.getText().toString(), bridge.getText().toString().trim(), secret);
                token.setText(""); config.enabled(true);
                if (!PhoneService.instance.startBridge()) throw new IllegalArgumentException(PhoneService.status);
                if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                    requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
                else moveTaskToBack(true);
            } catch (Exception e) { Toast.makeText(this, e instanceof IllegalArgumentException ? e.getMessage() : "保存失败，请重新填写令牌", Toast.LENGTH_LONG).show(); }
        });
        button(page, "停止桥接", v -> { config.enabled(false); if (PhoneService.instance != null) PhoneService.instance.stopBridge(); });
        button(page, "后台运行 / 电池优化设置", v -> startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)));
        status = text(page, "", 13);
        text(page, "iQOO 提示\n在系统设置中允许本应用后台运行，并按系统提供的选项开启自启动、取消电池限制。不同 OriginOS / Funtouch OS 版本菜单可能不同。\n\n定时任务需要手机处于亮屏且已解锁状态；应用不会绕过密码锁。系统可能仍会回收后台进程。\n\n此配置页禁止截图，桥接程序也拒绝读取或操作自己的配置页。启动后请返回桌面或目标应用。", 13);
    }
    @Override protected void onResume() { super.onResume(); handler.post(update); }
    @Override protected void onPause() { super.onPause(); handler.removeCallbacks(update); }
    @Override public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] results) {
        super.onRequestPermissionsResult(requestCode, permissions, results);
        if (requestCode == 1 && config.enabled()) moveTaskToBack(true);
    }
}
