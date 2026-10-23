package com.pocketagentdesk.remote;

import android.content.Intent;
import android.webkit.HttpAuthHandler;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.LinearLayout;
import androidx.appcompat.app.AlertDialog;
import org.junit.Test;
import org.junit.Before;
import org.junit.runner.RunWith;
import org.robolectric.Robolectric;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.RuntimeEnvironment;
import org.robolectric.annotation.Config;
import org.robolectric.util.ReflectionHelpers;
import static org.robolectric.Shadows.shadowOf;
import static org.junit.Assert.*;

@RunWith(RobolectricTestRunner.class)
@Config(sdk = 35)
public class FirstLoginTest {
    private android.webkit.WebResourceRequest request(String url, boolean gesture) {return request(url,gesture,true);}
    private android.webkit.WebResourceRequest request(String url, boolean gesture, boolean main) {
        return new android.webkit.WebResourceRequest() {
            public android.net.Uri getUrl(){return android.net.Uri.parse(url);}
            public boolean isForMainFrame(){return main;}
            public boolean isRedirect(){return false;}
            public boolean hasGesture(){return gesture;}
            public String getMethod(){return "GET";}
            public java.util.Map<String,String> getRequestHeaders(){return java.util.Collections.emptyMap();}
        };
    }
    @Test public void httpsTapOpensSystemBrowserWithoutHeadersAndPopupRequiresGesture() {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://relay.example/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()) {
            RemoteBrowserActivity activity=controller.get();WebView web=ReflectionHelpers.getField(activity,"web");
            assertTrue(web.getWebViewClient().shouldOverrideUrlLoading(web,request("https://news.example/article",true)));
            Intent external=shadowOf(activity).getNextStartedActivity();assertNotNull(external);
            assertEquals(Intent.ACTION_VIEW,external.getAction());assertEquals("https://news.example/article",external.getDataString());assertNull(external.getExtras());
            web.getWebViewClient().shouldOverrideUrlLoading(web,request("https://news.example/redirect",false));
            web.getWebViewClient().shouldOverrideUrlLoading(web,request("intent://danger",true));
            assertNull(shadowOf(activity).getNextStartedActivity());
            assertFalse(web.getWebChromeClient().onCreateWindow(web,false,false,null));
            android.os.Message result=android.os.Message.obtain(new android.os.Handler(android.os.Looper.getMainLooper()));
            WebView.WebViewTransport transport=ReflectionHelpers.callConstructor(WebView.WebViewTransport.class);result.obj=transport;
            assertTrue(web.getWebChromeClient().onCreateWindow(web,false,true,result));
            WebView popup=transport.getWebView();assertFalse(popup.getSettings().getJavaScriptEnabled());
            popup.getWebViewClient().shouldOverrideUrlLoading(popup,request("https://news.example/popup",false));
            assertEquals("https://news.example/popup",shadowOf(activity).getNextStartedActivity().getDataString());
        }
    }
    @Before public void skipNetworkUpdateCheck() {
        RuntimeEnvironment.getApplication().getSharedPreferences("app-updates",0)
            .edit().putLong("checked",System.currentTimeMillis()).commit();
    }
    @Test public void normalPageHasNoAddressToolbarAndOnlyFixedThemeSync() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), RemoteBrowserActivity.class)
            .putExtra("url", "https://example.com:8443/account");
        try (var controller = Robolectric.buildActivity(RemoteBrowserActivity.class, intent).setup()) {
            RemoteBrowserActivity activity = controller.get();
            assertEquals("遥应", activity.getApplicationInfo().loadLabel(activity.getPackageManager()).toString());
            assertNull(activity.getWindow().getDecorView().findViewWithTag("account-navigation"));
            WebView web = ReflectionHelpers.getField(activity, "web");
            web.getWebViewClient().onPageFinished(web,"https://example.com:8443/account");
            LinearLayout panel = ReflectionHelpers.getField(activity, "failurePanel");
            assertEquals(android.view.View.GONE,panel.getVisibility());
            assertTrue(shadowOf(web).getLastEvaluatedJavascript().contains("teleply.theme.v1"));
            assertTrue(shadowOf(web).getLastEvaluatedJavascript().contains("'system'"));
            ReflectionHelpers.callInstanceMethod(activity,"fail",ReflectionHelpers.ClassParameter.from(String.class,"Offline"));
            assertEquals(android.view.View.VISIBLE,panel.getVisibility());
            assertEquals(android.view.View.GONE,web.getVisibility());
        }
    }
    @Test public void appearanceOnlyAcceptsFixedModesAndPersists() {
        var context=RuntimeEnvironment.getApplication();
        ThemePolicy.save(context,"dark");assertEquals("dark",ThemePolicy.get(context));assertTrue(ThemePolicy.dark(context));
        ThemePolicy.save(context,"dark');fetch('https://evil')");assertEquals("dark",ThemePolicy.get(context));
        ThemePolicy.save(context,"light");assertFalse(ThemePolicy.dark(context));
        ThemePolicy.save(context,"system");assertEquals("system",ThemePolicy.get(context));
    }
    @Test public void remoteThemeIsNotInjectedIntoOtherOrigins() {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://example.com/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()) {
            WebView web=ReflectionHelpers.getField(controller.get(),"web");
            web.loadUrl("https://other.example/account");
            web.getWebViewClient().onPageFinished(web,"https://other.example/account");
            assertNull(shadowOf(web).getLastEvaluatedJavascript());
        }
    }
    @Test public void appearanceMessageIsOriginFrameEnumAndDocumentBound() throws Exception {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://example.com/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()){
            RemoteBrowserActivity activity=controller.get();
            WebView web=ReflectionHelpers.getField(activity,"web");
            ReflectionHelpers.setField(activity,"themeReady",true);
            String token=ReflectionHelpers.getField(activity,"documentToken");
            String message=new org.json.JSONObject().put("mode","dark").put("resolved","dark").put("document",token).toString();
            assertFalse(activity.onAppearanceMessage(message,android.net.Uri.parse("https://evil.example"),true));
            assertFalse(activity.onAppearanceMessage(message,android.net.Uri.parse("https://example.com"),false));
            assertFalse(activity.onAppearanceMessage(message.replace("dark","invalid"),android.net.Uri.parse("https://example.com"),true));
            assertFalse(activity.onAppearanceMessage(message.replace(token,"old-document"),android.net.Uri.parse("https://example.com"),true));
            assertFalse(activity.onAppearanceMessage("{",android.net.Uri.parse("https://example.com"),true));
            assertTrue(activity.onAppearanceMessage(message,android.net.Uri.parse("https://example.com"),true));
            assertEquals("dark",ThemePolicy.get(activity));
            assertFalse(activity.acceptThemeRead(org.json.JSONObject.quote(message.replace("dark","light")),"https://example.com/account",token));
            assertEquals("dark",ThemePolicy.get(activity));
            assertTrue((Boolean)ReflectionHelpers.getField(activity,"themeEventsActive"));
            LinearLayout root=ReflectionHelpers.getField(activity,"root");
            assertEquals(0xff000000,((android.graphics.drawable.ColorDrawable)root.getBackground()).getColor());
            String light=message.replace("dark","light");
            assertTrue(activity.onAppearanceMessage(light,android.net.Uri.parse("https://example.com"),true));
            assertEquals(0xffffffff,((android.graphics.drawable.ColorDrawable)root.getBackground()).getColor());
            web.getWebViewClient().onPageStarted(web,"https://example.com/account",null);
            assertFalse(activity.onAppearanceMessage(message,android.net.Uri.parse("https://example.com"),true));
            assertEquals("light",ThemePolicy.get(activity));
        }
    }
    @Test public void finishedPageSeedsThemeOnlyOnce() {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://example.com/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()){
            RemoteBrowserActivity activity=controller.get();WebView web=ReflectionHelpers.getField(activity,"web");
            web.getWebViewClient().onPageFinished(web,"https://example.com/account");
            String first=shadowOf(web).getLastEvaluatedJavascript();
            ThemePolicy.save(activity,"dark");
            web.getWebViewClient().onPageFinished(web,"https://example.com/account");
            assertEquals(first,shadowOf(web).getLastEvaluatedJavascript());
        }
    }
    @Test public void aboutIsAccessibleFromRemoteSettingsOnlyByTrustedGesture() {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://example.com/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()){
            RemoteBrowserActivity activity=controller.get();WebView web=ReflectionHelpers.getField(activity,"web");
            web.getWebViewClient().onPageFinished(web,"https://example.com/account");
            assertTrue(shadowOf(web).getLastEvaluatedJavascript().contains("TeleplyAbout.mount"));
            String token=ReflectionHelpers.getField(activity,"documentToken"),url="teleply-app://about?document="+token;
            assertTrue(activity.handleAppAction(request(url,true,false)));assertNull(ReflectionHelpers.getField(activity,"aboutDialog"));
            assertTrue(activity.handleAppAction(request(url,false)));assertNull(ReflectionHelpers.getField(activity,"aboutDialog"));
            assertTrue(activity.handleAppAction(request("teleply-app://about?document=stale",true)));assertNull(ReflectionHelpers.getField(activity,"aboutDialog"));
            assertTrue(activity.handleAppAction(request(url,true)));
            AlertDialog dialog=ReflectionHelpers.getField(activity,"aboutDialog");assertTrue(dialog.isShowing());
            assertEquals("检查更新",dialog.getButton(AlertDialog.BUTTON_POSITIVE).getText().toString());
            assertTrue(((android.widget.TextView)dialog.findViewById(android.R.id.message)).getText().toString().contains("当前版本："));
        }
    }
    @Test public void offlineErrorStillHasSettingsAndAboutWithoutLogin() {
        Intent intent=new Intent(RuntimeEnvironment.getApplication(),RemoteBrowserActivity.class).putExtra("url","https://example.com/account");
        try(var controller=Robolectric.buildActivity(RemoteBrowserActivity.class,intent).setup()){
            RemoteBrowserActivity activity=controller.get();ReflectionHelpers.callInstanceMethod(activity,"fail",ReflectionHelpers.ClassParameter.from(String.class,"Offline"));
            LinearLayout panel=ReflectionHelpers.getField(activity,"failurePanel");android.widget.Button settings=null;
            for(int i=0;i<panel.getChildCount();i++){android.view.View view=panel.getChildAt(i);if(view instanceof android.widget.Button&&"设置".contentEquals(((android.widget.Button)view).getText()))settings=(android.widget.Button)view;}
            assertNotNull(settings);settings.performClick();
            AlertDialog menu=ReflectionHelpers.getField(activity,"appSettingsDialog");assertTrue(menu.isShowing());
            menu.getListView().performItemClick(menu.getListView().getAdapter().getView(0,null,menu.getListView()),0,0);
            AlertDialog about=ReflectionHelpers.getField(activity,"aboutDialog");assertTrue(about.isShowing());assertTrue(about.getButton(AlertDialog.BUTTON_POSITIVE).isEnabled());
        }
    }
    @Test public void freshBrowserShowsNativeCredentialsAndCanCancelWithoutLogin() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), RemoteBrowserActivity.class)
            .putExtra("url", "https://example.com/");
        try (var controller = Robolectric.buildActivity(RemoteBrowserActivity.class, intent).setup()) {
            RemoteBrowserActivity activity = controller.get();
            WebView web = ReflectionHelpers.getField(activity, "web");
            assertEquals("https://example.com/", web.getUrl());
            HttpAuthHandler handler = ReflectionHelpers.callConstructor(HttpAuthHandler.class);
            web.getWebViewClient().onReceivedHttpAuthRequest(web, handler, "example.com", "restricted");
            AlertDialog dialog = ReflectionHelpers.getField(activity, "authDialog");
            assertNotNull(dialog);
            assertTrue(dialog.isShowing());
            // Empty submission must not dismiss the native login prompt.
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick();
            assertTrue(dialog.isShowing());
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).performClick();
            shadowOf(android.os.Looper.getMainLooper()).idle();
            assertNull(ReflectionHelpers.getField(activity, "authHandler"));
        }
    }
    @Test public void foreignHostCannotRequestCredentials() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), RemoteBrowserActivity.class)
            .putExtra("url", "https://example.com/");
        try (var controller = Robolectric.buildActivity(RemoteBrowserActivity.class, intent).setup()) {
            RemoteBrowserActivity activity = controller.get();
            WebView web = ReflectionHelpers.getField(activity, "web");
            HttpAuthHandler handler = ReflectionHelpers.callConstructor(HttpAuthHandler.class);
            web.getWebViewClient().onReceivedHttpAuthRequest(web, handler, "other.example.com", "restricted");
            assertNull(ReflectionHelpers.getField(activity, "authDialog"));
        }
    }
}
