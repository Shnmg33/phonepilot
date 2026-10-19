package com.phonepilot.bridge;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
public class StopReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        new Config(context).enabled(false);
        if (PhoneService.instance != null) PhoneService.instance.stopBridge();
    }
}
