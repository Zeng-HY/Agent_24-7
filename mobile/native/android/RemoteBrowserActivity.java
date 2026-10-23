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
import java.util.Collections;
import java.util.UUID;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import androidx.webkit.WebMessageCompat;
import org.json.JSONObject;
import org.json.JSONTokener;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsControllerCompat;

/** Remote WebView: no Capacitor or general JavascriptInterface; only a restricted appearance message. */
public class RemoteBrowserActivity extends AppCompatActivity {
    private WebView web;
    private LinearLayout root;
    private boolean themeReady,themeMessaging,themeEventsActive,foreground;
    private String documentToken=UUID.randomUUID().toString(),seededToken=null,resolvedTheme=null;
    private final android.os.Handler themeHandler=new android.os.Handler(android.os.Looper.getMainLooper());
    private final Runnable themePoll=new Runnable(){public void run(){if(!foreground)return;syncTheme();if(!themeEventsActive)themeHandler.postDelayed(this,500);}};
    private void applyTheme(){
        boolean dark=resolvedTheme==null?ThemePolicy.dark(this):"dark".equals(resolvedTheme);
        ThemePolicy.apply(this,root,dark);
        if(web!=null)web.setBackgroundColor(dark?0xff000000:0xffffffff);
        if(failurePanel!=null)ThemePolicy.text(failurePanel,dark);
    }
    // This listener accepts appearance only; it exposes no general native API to remote pages.
    private void installAppearanceChannel(){
        try{
            if(WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)){
                Uri uri=Uri.parse(entry);String origin=uri.getScheme()+"://"+uri.getAuthority();
                WebViewCompat.addWebMessageListener(web,"TeleplyAppearance",Collections.singleton(origin),
                    (view,message,sourceOrigin,isMainFrame,reply)->{if(message.getType()==WebMessageCompat.TYPE_STRING)onAppearanceMessage(message.getData(),sourceOrigin,isMainFrame);});
                themeMessaging=true;
            }
        }catch(RuntimeException|LinkageError unavailable){themeMessaging=false;}
    }
    boolean onAppearanceMessage(String value,Uri sourceOrigin,boolean mainFrame){
        if(!receiveAppearance(value,sourceOrigin,mainFrame))return false;
        themeEventsActive=true;themeHandler.removeCallbacks(themePoll);return true;
    }
    boolean receiveAppearance(String value,Uri sourceOrigin,boolean mainFrame){
        if(!mainFrame||!themeReady||loadFailed||isFinishing()||isDestroyed()||web==null||value==null||value.length()>256||
            !BrowserPolicy.sameOrigin(entry,String.valueOf(sourceOrigin))||!BrowserPolicy.sameOrigin(entry,web.getUrl()))return false;
        try{
            JSONObject data=new JSONObject(value);String mode=data.getString("mode"),resolved=data.getString("resolved");
            if(data.length()!=3||!documentToken.equals(data.getString("document"))||!ThemePolicy.valid(mode)||
                !("light".equals(resolved)||"dark".equals(resolved))||(!"system".equals(mode)&&!mode.equals(resolved)))return false;
            ThemePolicy.save(this,mode);resolvedTheme=resolved;applyTheme();return true;
        }catch(Exception invalid){return false;}
    }
    private void syncTheme(){
        if(themeEventsActive||!themeReady||web==null||!BrowserPolicy.sameOrigin(entry,web.getUrl()))return;
        final String url=web.getUrl(),token=documentToken;
        web.evaluateJavascript("window.TeleplyTheme ? JSON.stringify({mode:window.TeleplyTheme.get(),resolved:document.documentElement.dataset.theme,document:window.__teleplyAppearanceDocument}) : null",value->{
            acceptThemeRead(value,url,token);
        });
    }
    boolean acceptThemeRead(String value,String url,String token){
        if(themeEventsActive||!token.equals(documentToken)||web==null||!url.equals(web.getUrl()))return false;
        try{Object raw=new JSONTokener(value).nextValue();return raw instanceof String&&receiveAppearance((String)raw,Uri.parse(url),true);}catch(Exception invalid){return false;}
    }
    private void seedTheme(){
        if(web==null||!BrowserPolicy.sameOrigin(entry,web.getUrl())||documentToken.equals(seededToken))return;
        final String url=web.getUrl(),mode=ThemePolicy.get(this),token=documentToken;
        seededToken=token;themeReady=true;
        web.evaluateJavascript(aboutUi()+";if(window.TeleplyAbout)window.TeleplyAbout.mount(\"teleply-app://about?document="+token+"\");"+"(()=>{window.__teleplyAppearanceDocument='"+token+"';try{localStorage.setItem('teleply.theme.v1','"+mode+"')}catch(e){};if(window.TeleplyTheme)window.TeleplyTheme.set('"+mode+"');return true})()",result->{
            if(!token.equals(documentToken)||!url.equals(web.getUrl()))return;
            syncTheme();web.postVisualStateCallback(0,new WebView.VisualStateCallback(){public void onComplete(long id){if(!isFinishing()&&token.equals(documentToken))web.setAlpha(1f);}});
        });
    }
    private String nativeAboutUi=null;
    private AlertDialog aboutDialog,appSettingsDialog;
    private String aboutUi(){
        if(nativeAboutUi!=null)return nativeAboutUi;
        try(java.io.InputStream input=getAssets().open("public/native-about.js");java.io.ByteArrayOutputStream output=new java.io.ByteArrayOutputStream()){
            byte[] block=new byte[4096];int count;while((count=input.read(block))!=-1)output.write(block,0,count);
            nativeAboutUi=output.toString("UTF-8");
        }catch(java.io.IOException unavailable){nativeAboutUi="";}
        return nativeAboutUi;
    }
    private void showAbout(){if(aboutDialog==null||!aboutDialog.isShowing())aboutDialog=AppUpdater.showAbout(this);}
    private void showAppSettings(){appSettingsDialog=ThemePolicy.dialog(this).setTitle("设置").setItems(new String[]{"关于遥应"},(d,w)->showAbout()).setNegativeButton("关闭",null).show();}
    boolean handleAppAction(WebResourceRequest request){
        Uri uri=request.getUrl();if(!"teleply-app".equals(uri.getScheme()))return false;
        if(request.isForMainFrame()&&request.hasGesture()&&themeReady&&!loadFailed&&BrowserPolicy.sameOrigin(entry,web.getUrl())&&
            "about".equals(uri.getHost())&&uri.getUserInfo()==null&&uri.getPort()==-1&&(uri.getPath()==null||uri.getPath().isEmpty())&&uri.getFragment()==null&&
            ("document="+documentToken).equals(uri.getEncodedQuery()))showAbout();
        return true;
    }
    private TextView status;
    private LinearLayout failurePanel;
    private String entry;
    private ValueCallback<Uri[]> fileResult;
    private PermissionRequest mediaRequest;
    private AlertDialog authDialog;
    private HttpAuthHandler authHandler;
    private boolean loadFailed;
    private int authAttempts;
    private static final int FILE = 41, MEDIA = 42;
    private String accountUrl() { Uri u = Uri.parse(entry); return u.getScheme() + "://" + u.getAuthority() + "/account"; }
    private void openExternal(String url) {
        if (!BrowserPolicy.externalLink(entry, url)) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE)); }
        catch (android.content.ActivityNotFoundException e) { Toast.makeText(this, "没有可用的浏览器", Toast.LENGTH_SHORT).show(); }
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        entry = getIntent().getStringExtra("url");
        if (!BrowserPolicy.validEntry(entry)) { finish(); return; }
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xffffffff);
        WindowCompat.setDecorFitsSystemWindows(getWindow(), false);
        ViewCompat.setOnApplyWindowInsetsListener(root, (view, insets) -> {
            Insets p = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.ime());
            view.setPadding(p.left, p.top, p.right, p.bottom);
            return WindowInsetsCompat.CONSUMED;
        });
        failurePanel = new LinearLayout(this);
        failurePanel.setOrientation(LinearLayout.VERTICAL);
        failurePanel.setGravity(android.view.Gravity.CENTER);
        failurePanel.setPadding(32, 32, 32, 32);
        failurePanel.setVisibility(View.GONE);
        status = new TextView(this); status.setTextColor(0xff333333); status.setTextSize(16);
        status.setGravity(android.view.Gravity.CENTER); status.setPadding(0, 0, 0, 20);
        failurePanel.addView(status);
        for (String action : new String[]{"重试", "账号", "设置", "连接设置"}) {
            Button button = new Button(this); button.setText(action); button.setMinHeight(48);
            button.setOnClickListener(v -> {
                if(action.equals("设置"))showAppSettings();
                else if (action.equals("连接设置")) finish();
                else if (action.equals("账号")) web.loadUrl(accountUrl());
                else { authAttempts = 0; web.reload(); }
            });
            failurePanel.addView(button);
        }
        root.addView(failurePanel, new LinearLayout.LayoutParams(-1, 0, 1));
        web = new WebView(this);
        root.addView(web, new LinearLayout.LayoutParams(-1, 0, 1));
        setContentView(root);
        getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        WindowInsetsControllerCompat bars = WindowCompat.getInsetsController(getWindow(), root);
        bars.setAppearanceLightStatusBars(true);
        bars.setAppearanceLightNavigationBars(true);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSupportMultipleWindows(true);
        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        installAppearanceChannel();applyTheme();
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                if(handleAppAction(request))return true;
                if (BrowserPolicy.sameOrigin(entry, request.getUrl().toString())) return false;
                if (request.isForMainFrame() && request.hasGesture()) openExternal(request.getUrl().toString());
                status.setText("已阻止打开其他地址");
                return true;
            }
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                if (!BrowserPolicy.sameOrigin(entry, url)) { view.stopLoading(); fail("已阻止打开其他地址"); return; }
                themeReady=false;themeEventsActive=false;themeHandler.removeCallbacks(themePoll);if(foreground)themeHandler.post(themePoll);documentToken=UUID.randomUUID().toString();seededToken=null;resolvedTheme=null;applyTheme();web.setAlpha(0f);
                loadFailed = false; failurePanel.setVisibility(View.GONE); web.setVisibility(View.VISIBLE);
            }
            @Override public void onPageFinished(WebView view, String url) {
                if(!url.equals(view.getUrl()))return;
                seedTheme();
                CookieManager.getInstance().flush();
                if (!loadFailed) failurePanel.setVisibility(View.GONE);
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
                handler.cancel(); fail("证书无效，已停止连接");
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) fail("连不上服务");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request, WebResourceResponse response) {
                if (!request.isForMainFrame()) return;
                int code = response.getStatusCode();
                fail(code == 401 ? "请重新登录"
                    : code == 403 ? "没有可用的电脑"
                    : code == 404 ? "页面不存在"
                    : code == 502 || code == 503 || code == 504 ? "电脑不在线"
                    : "出错了（HTTP " + code + "）");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onCreateWindow(WebView view, boolean dialog, boolean gesture, android.os.Message result) {
                if (!gesture) return false;
                // A target=_blank tap gets a URL-only temporary view, never a bridge or copied credentials.
                WebView popup = new WebView(RemoteBrowserActivity.this);
                popup.getSettings().setAllowFileAccess(false);
                popup.getSettings().setAllowContentAccess(false);
                popup.setWebViewClient(new WebViewClient() {
                    @Override public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                        String url = request.getUrl().toString();
                        if (request.isForMainFrame()) {
                            if (BrowserPolicy.sameOrigin(entry, url)) web.loadUrl(url);
                            else openExternal(url);
                        }
                        v.post(v::destroy);
                        return true;
                    }
                });
                ((WebView.WebViewTransport) result.obj).setWebView(popup);
                result.sendToTarget();
                return true;
            }
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
                catch (android.content.ActivityNotFoundException e) { fileResult.onReceiveValue(null); fileResult = null; status.setText("没有可用的文件选择器"); }
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
            @Override public void handleOnBackPressed() {
                if (loadFailed) { web.loadUrl(accountUrl()); return; }
                web.evaluateJavascript("(()=>{const d=document.querySelector('dialog[open]');if(d){d.close();return true;}const s=document.querySelector('.sheet.is-open');if(s&&typeof closeSheet==='function'){closeSheet(s.id);return true;}if(document.body.classList.contains('chat-open')){history.back();return true;}return false;})()", value -> {
                    if ("true".equals(value)) return;
                    String current=web.getUrl();
                    if (current!=null && Uri.parse(current).getPath().startsWith("/d/")) web.loadUrl(accountUrl());
                    else if (web.canGoBack()) web.goBack(); else finish();
                });
            }
        });
        web.loadUrl(entry);
        AppUpdater.check(this, false);
    }

    private void fail(String text) { loadFailed = true; status.setText(text); failurePanel.setVisibility(View.VISIBLE); web.setVisibility(View.GONE); }

    private void askForLogin(HttpAuthHandler handler) {
        if (authHandler != null) { handler.cancel(); return; }
        authHandler = handler;
        LinearLayout fields = new LinearLayout(this); fields.setOrientation(LinearLayout.VERTICAL); fields.setPadding(40, 8, 40, 0);
        TextView help = new TextView(this);
        help.setText((authAttempts++ > 0 ? "账号或密码不对\n" : "") + Uri.parse(entry).getAuthority());
        EditText user = new EditText(this); user.setHint("服务账号"); user.setSingleLine(true);
        user.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        EditText password = new EditText(this); password.setHint("服务密码"); password.setSingleLine(true);
        password.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        fields.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);
        fields.addView(help); fields.addView(user); fields.addView(password);
        ThemePolicy.text(fields,ThemePolicy.dark(this));
        authDialog = ThemePolicy.dialog(this).setTitle("服务访问验证").setView(fields)
            .setPositiveButton("登录", null).setNegativeButton("暂不连接", (d, w) -> cancelAuth())
            .setOnCancelListener(d -> cancelAuth()).create();
        authDialog.setOnShowListener(d -> authDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v -> {
            String name = user.getText().toString().trim(), secret = password.getText().toString();
            if (name.isEmpty() || secret.isEmpty()) { password.setError("请填写账号和密码"); return; }
            HttpAuthHandler pending = authHandler; authHandler = null;
            password.setText(""); authDialog.dismiss(); authDialog = null;
            // Credentials are handed to WebView for this challenge, never stored by the launcher or logged.
            if (pending != null) pending.proceed(name, secret);
        }));
        web.setVisibility(View.VISIBLE); authDialog.show();
    }

    private void cancelAuth() {
        if (authHandler != null) { authHandler.cancel(); authHandler = null; }
        fail("请先登录");
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
    @Override protected void onPause() { foreground=false;themeHandler.removeCallbacks(themePoll); if (web != null) { web.onPause(); CookieManager.getInstance().flush(); } super.onPause(); }
    @Override protected void onResume() {
        super.onResume();foreground=true;if(web!=null)web.onResume();resolvedTheme=null;applyTheme();themeHandler.removeCallbacks(themePoll);
        if(!themeEventsActive)themeHandler.post(themePoll);refreshAppearance();
    }
    private void refreshAppearance(){
        if(themeReady&&web!=null&&BrowserPolicy.sameOrigin(entry,web.getUrl()))
            web.evaluateJavascript("if(window.TeleplyTheme)window.TeleplyTheme.set(window.TeleplyTheme.get())",null);
    }
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration){
        super.onConfigurationChanged(configuration);resolvedTheme=null;applyTheme();refreshAppearance();
    }
    @Override protected void onDestroy() {
        themeHandler.removeCallbacks(themePoll);
        if (authHandler != null) { authHandler.cancel(); authHandler = null; }
        if (authDialog != null) authDialog.dismiss();
        if(aboutDialog!=null)aboutDialog.dismiss();
        if(appSettingsDialog!=null)appSettingsDialog.dismiss();
        if (fileResult != null) fileResult.onReceiveValue(null);
        if (mediaRequest != null) mediaRequest.deny();
        if (web != null) { if(themeMessaging)WebViewCompat.removeWebMessageListener(web,"TeleplyAppearance");web.stopLoading(); web.destroy(); }
        super.onDestroy();
    }
}
