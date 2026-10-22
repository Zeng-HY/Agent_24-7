package com.pocketagentdesk.remote;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.webkit.*;
import android.widget.*;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import java.util.ArrayList;

/** Plain remote WebView. Never attach Capacitor or a JavascriptInterface to it. */
public class RemoteBrowserActivity extends AppCompatActivity {
    private WebView web;
    private TextView status;
    private String entry;
    private ValueCallback<Uri[]> fileResult;
    private PermissionRequest mediaRequest;
    private AlertDialog authDialog;
    private HttpAuthHandler authHandler;
    private boolean loadFailed;
    private int authAttempts;
    private static final int FILE = 41, MEDIA = 42;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        entry = getIntent().getStringExtra("url");
        if (!BrowserPolicy.validEntry(entry)) { finish(); return; }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xfff6f8fc);
        ViewCompat.setOnApplyWindowInsetsListener(root, (view, insets) -> {
            Insets p = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.ime());
            view.setPadding(p.left, p.top, p.right, p.bottom);
            return insets;
        });
        LinearLayout bar = new LinearLayout(this);
        Button close = new Button(this); close.setText("返回"); close.setOnClickListener(v -> finish());
        TextView host = new TextView(this); host.setText(Uri.parse(entry).getAuthority()); host.setTextColor(0xff243a57);
        Button reload = new Button(this); reload.setText("重试"); reload.setOnClickListener(v -> { authAttempts = 0; web.loadUrl(entry); });
        bar.addView(close); bar.addView(host, new LinearLayout.LayoutParams(0, -2, 1)); bar.addView(reload);
        bar.setGravity(android.view.Gravity.CENTER_VERTICAL);
        root.addView(bar);
        status = new TextView(this); status.setTextColor(0xff243a57); status.setPadding(24, 12, 24, 12);
        root.addView(status);
        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if (BrowserPolicy.sameOrigin(entry, request.getUrl().toString())) return false;
                status.setText("已停止跳转到其他服务地址。请返回启动页核对地址。");
                return true;
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                if (!BrowserPolicy.sameOrigin(entry, url)) { view.stopLoading(); fail("已停止跳转到其他服务地址。"); return; }
                loadFailed = false; web.setVisibility(View.VISIBLE); status.setText("正在连接…");
            }
            @Override public void onPageFinished(WebView view, String url) {
                CookieManager.getInstance().flush();
                if (!loadFailed) status.setText("首次连接请完成网页中的电脑配对。关闭窗口不会退出账号。");
            }
            @Override public void onReceivedHttpAuthRequest(WebView view, HttpAuthHandler handler, String host, String realm) {
                // Only authenticate the explicitly selected HTTPS origin, never a cross-origin resource.
                String activeUrl = view.getUrl() == null ? entry : view.getUrl();
                if (!Uri.parse(entry).getHost().equalsIgnoreCase(host) || !BrowserPolicy.sameOrigin(entry, activeUrl)) {
                    handler.cancel(); return;
                }
                askForLogin(handler);
            }
            @Override public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
                handler.cancel(); fail("证书验证失败，已停止连接。请让管理员检查服务证书，不要关闭安全验证。");
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) fail("暂时连不上服务。检查网络和服务地址，再点重试；公网入口无需 Tailscale。");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (!request.isForMainFrame()) return;
                int code = response.getStatusCode();
                fail(code == 401 ? "尚未通过服务登录。点重试重新输入管理员提供的账号密码。"
                    : code == 404 ? "这个入口尚未启用。返回启动页，使用首次连接入口。"
                    : "服务返回 HTTP " + code + "。稍后重试，或联系服务管理员。");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileResult != null) fileResult.onReceiveValue(null);
                fileResult = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
                String[] types = params.getAcceptTypes();
                ArrayList<String> mime = new ArrayList<>();
                for (String type : types) if (type.contains("/")) mime.add(type);
                if (!mime.isEmpty()) intent.putExtra(Intent.EXTRA_MIME_TYPES, mime.toArray(new String[0]));
                intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(intent, FILE); }
                catch (android.content.ActivityNotFoundException e) { fileResult.onReceiveValue(null); fileResult = null; status.setText("未找到文件选择器，请安装系统文件应用。"); }
                return true;
            }
            @Override public void onPermissionRequest(PermissionRequest request) {
                runOnUiThread(() -> requestMedia(request));
            }
            @Override public void onPermissionRequestCanceled(PermissionRequest request) {
                if (mediaRequest == request) mediaRequest = null;
            }
        });
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() { if (web.canGoBack()) web.goBack(); else finish(); }
        });
        web.loadUrl(entry);
    }

    private void fail(String text) { loadFailed = true; status.setText(text); web.setVisibility(View.INVISIBLE); }

    private void askForLogin(HttpAuthHandler handler) {
        if (authHandler != null) { handler.cancel(); return; }
        authHandler = handler;
        LinearLayout fields = new LinearLayout(this); fields.setOrientation(LinearLayout.VERTICAL); fields.setPadding(40, 8, 40, 0);
        TextView help = new TextView(this);
        help.setText((authAttempts++ > 0 ? "上次登录未通过，请检查账号密码。\n" : "")
            + "服务地址：" + Uri.parse(entry).getAuthority() + "\n这是服务管理员提供的入口账号，不是手机或 Tailscale 账号。登录后还需输入电脑配对码。");
        EditText user = new EditText(this); user.setHint("服务账号"); user.setSingleLine(true);
        user.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        EditText password = new EditText(this); password.setHint("服务密码"); password.setSingleLine(true);
        password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        fields.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        fields.addView(help); fields.addView(user); fields.addView(password);
        authDialog = new AlertDialog.Builder(this).setTitle("首次连接 · 服务登录").setView(fields)
            .setPositiveButton("登录", null).setNegativeButton("暂不连接", (d, w) -> cancelAuth())
            .setOnCancelListener(d -> cancelAuth()).create();
        authDialog.setOnShowListener(d -> authDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String name = user.getText().toString().trim(), secret = password.getText().toString();
            if (name.isEmpty() || secret.isEmpty()) { password.setError("请填写服务账号和密码"); return; }
            HttpAuthHandler pending = authHandler; authHandler = null;
            password.setText(""); authDialog.dismiss(); authDialog = null;
            // Credentials are handed to WebView for this challenge, never stored by the launcher or logged.
            if (pending != null) pending.proceed(name, secret);
        }));
        web.setVisibility(View.VISIBLE); authDialog.show();
    }

    private void cancelAuth() {
        if (authHandler != null) { authHandler.cancel(); authHandler = null; }
        fail("尚未登录。向服务管理员获取入口账号密码后，点重试。新手机不需要先安装 Tailscale。");
    }
    private void requestMedia(PermissionRequest request) {
        if (mediaRequest != null || !BrowserPolicy.sameOrigin(entry, request.getOrigin().toString())) { request.deny(); return; }
        ArrayList<String> permissions = new ArrayList<>();
        for (String resource : request.getResources()) {
            if (PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resource)) permissions.add(Manifest.permission.RECORD_AUDIO);
            else if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(resource)) permissions.add(Manifest.permission.CAMERA);
            else { request.deny(); return; }
        }
        mediaRequest = request;
        requestPermissions(permissions.toArray(new String[0]), MEDIA);
    }
    @Override public void onRequestPermissionsResult(int code, String[] permissions, int[] grants) {
        super.onRequestPermissionsResult(code, permissions, grants);
        if (code == MEDIA && mediaRequest != null) {
            boolean allowed = grants.length == permissions.length && grants.length > 0;
            for (int result : grants) allowed &= result == PackageManager.PERMISSION_GRANTED;
            if (allowed) mediaRequest.grant(mediaRequest.getResources()); else mediaRequest.deny();
            mediaRequest = null;
        }
    }
    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == FILE && fileResult != null) {
            ArrayList<Uri> uris = new ArrayList<>();
            if (result == RESULT_OK && data != null) {
                if (data.getClipData() != null) for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
                else if (data.getData() != null) uris.add(data.getData());
            }
            // Only grant the content URIs explicitly selected through Android's picker.
            uris.removeIf(uri -> !"content".equals(uri.getScheme()));
            fileResult.onReceiveValue(uris.isEmpty() ? null : uris.toArray(new Uri[0])); fileResult = null;
        }
    }
    @Override protected void onPause() { if (web != null) { web.onPause(); CookieManager.getInstance().flush(); } super.onPause(); }
    @Override protected void onResume() { super.onResume(); if (web != null) { web.onResume(); web.setVisibility(View.VISIBLE); } }
    @Override protected void onDestroy() {
        if (authHandler != null) { authHandler.cancel(); authHandler = null; }
        if (authDialog != null) authDialog.dismiss();
        if (fileResult != null) fileResult.onReceiveValue(null);
        if (mediaRequest != null) mediaRequest.deny();
        if (web != null) { web.stopLoading(); web.destroy(); }
        super.onDestroy();
    }
}
