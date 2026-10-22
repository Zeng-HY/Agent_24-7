package com.pocketagentdesk.remote;

import android.content.Intent;
import android.webkit.HttpAuthHandler;
import android.webkit.WebView;
import android.widget.EditText;
import android.widget.LinearLayout;
import androidx.appcompat.app.AlertDialog;
import org.junit.Test;
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
    @Test public void accountNavigationReturnsToTheSameOriginAccountPage() {
        Intent intent = new Intent(RuntimeEnvironment.getApplication(), RemoteBrowserActivity.class)
            .putExtra("url", "https://example.com:8443/");
        try (var controller = Robolectric.buildActivity(RemoteBrowserActivity.class, intent).setup()) {
            RemoteBrowserActivity activity = controller.get();
            activity.getWindow().getDecorView().findViewWithTag("account-navigation").performClick();
            WebView web = ReflectionHelpers.getField(activity, "web");
            assertEquals("https://example.com:8443/account", web.getUrl());
            web.getWebViewClient().onPageFinished(web, "https://example.com:8443/account");
            assertTrue(shadowOf(web).getLastEvaluatedJavascript().contains("data-pad-theme"));
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
