package com.pocketagentdesk.remote;

import android.content.Intent;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "RemoteBrowser")
public class RemoteBrowserPlugin extends Plugin {
    @PluginMethod
    public void getTheme(PluginCall call) {
        com.getcapacitor.JSObject result=new com.getcapacitor.JSObject();result.put("mode",ThemePolicy.get(getContext()));call.resolve(result);
    }
    @PluginMethod
    public void setTheme(PluginCall call) {
        String mode=call.getString("mode", "");
        if(!ThemePolicy.valid(mode)){call.reject("Invalid theme");return;}
        ThemePolicy.save(getContext(),mode);
        getActivity().runOnUiThread(()->{ThemePolicy.apply(getActivity(),getBridge().getWebView());call.resolve();});
    }
    @PluginMethod
    public void showAbout(PluginCall call) {
        getActivity().runOnUiThread(()->{AppUpdater.showAbout(getActivity());call.resolve();});
    }
    @PluginMethod
    public void checkUpdate(PluginCall call) {
        getActivity().runOnUiThread(() -> { AppUpdater.check(getActivity(), true); call.resolve(); });
    }
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
