package com.pocketagentdesk.remote;

import android.content.Intent;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "RemoteBrowser")
public class RemoteBrowserPlugin extends Plugin {
    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url", "");
        if (!BrowserPolicy.validEntry(url)) { call.reject("仅支持 HTTPS 服务入口"); return; }
        getActivity().runOnUiThread(() -> {
            getActivity().startActivity(new Intent(getContext(), RemoteBrowserActivity.class).putExtra("url", url));
            call.resolve();
        });
    }
}
