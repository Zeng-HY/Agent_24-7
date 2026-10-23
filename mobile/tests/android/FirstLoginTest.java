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
    private android.webkit.WebResourceRequest request(String url, boolean gesture) {
        return new android.webkit.WebResourceRequest() {
            public android.net.Uri getUrl(){return android.net.Uri.parse(url);}
            public boolean isForMainFrame(){return true;}
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
    @Test public void normalPageHasNoNativeAddressToolbarOrInjectedTheme() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), RemoteBrowserActivity.class)
            .putExtra("url", "https://example.com:8443/account");
        try (var controller = Robolectric.buildActivity(RemoteBrowserActivity.class, intent).setup()) {
            RemoteBrowserActivity activity = controller.get();
            assertNull(activity.getWindow().getDecorView().findViewWithTag("account-navigation"));
            WebView web = ReflectionHelpers.getField(activity, "web");
            web.getWebViewClient().onPageFinished(web,"https://example.com:8443/account");
            LinearLayout panel = ReflectionHelpers.getField(activity, "failurePanel");
            assertEquals(android.view.View.GONE,panel.getVisibility());
            assertNull(shadowOf(web).getLastEvaluatedJavascript());
            ReflectionHelpers.callInstanceMethod(activity,"fail",ReflectionHelpers.ClassParameter.from(String.class,"Offline"));
            assertEquals(android.view.View.VISIBLE,panel.getVisibility());
            assertEquals(android.view.View.GONE,web.getVisibility());
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
