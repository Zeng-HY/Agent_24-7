package com.pocketagentdesk.remote;

import android.app.Activity;
import androidx.appcompat.app.AlertDialog;
import android.content.ClipData;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.ProgressBar;
import android.widget.Toast;
import androidx.core.content.FileProvider;
import java.io.*;
import java.net.URL;
import javax.net.ssl.HttpsURLConnection;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.concurrent.atomic.AtomicBoolean;

/** Native-only updater: no remote JavaScript interface, no silent installation. */
final class AppUpdater {
    private static final AtomicBoolean busy=new AtomicBoolean();
    private static final long INTERVAL=24L*60*60*1000;
    private static boolean alive(Activity a) { return !a.isFinishing() && !a.isDestroyed(); }
    private static void message(Activity a,String text) {
        if(alive(a)) Toast.makeText(a,text,Toast.LENGTH_LONG).show();
    }
    static AlertDialog showAbout(Activity activity) {
        String version;
        try { PackageInfo info=activity.getPackageManager().getPackageInfo(activity.getPackageName(),0);
            version=info.versionName+" / code "+version(info);
        } catch(PackageManager.NameNotFoundException impossible) {version="无法读取版本";}
        AlertDialog dialog=ThemePolicy.dialog(activity).setTitle("关于遥应").setMessage("当前版本："+version)
            .setPositiveButton("检查更新",(d,w)->check(activity,true)).setNegativeButton("关闭",null).create();
        dialog.show();return dialog;
    }
    static void check(Activity a,boolean manual) {
        var prefs=a.getSharedPreferences("app-updates",0);
        long now=System.currentTimeMillis();
        if(!manual && now-prefs.getLong("checked",0)<INTERVAL) return;
        if(!busy.compareAndSet(false,true)) { if(manual) message(a,"正在检查或下载更新"); return; }
        if(manual) message(a,"正在检查更新…");
        new Thread(() -> {
            try {
                PackageInfo current=a.getPackageManager().getPackageInfo(a.getPackageName(),0);
                boolean preview=(a.getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE)!=0;
                UpdatePolicy.Release update=UpdatePolicy.choose(readMetadata(),version(current),preview);
                prefs.edit().putLong("checked",now).apply();
                a.runOnUiThread(() -> {
                    busy.set(false);
                    if(!alive(a)) return;
                    if(update==null) { if(manual) message(a,"当前已是最新可用版本"); return; }
                    if(!manual && prefs.getLong("skipped",0)==update.code) return;
                    String detail=String.format(java.util.Locale.ROOT,"%.1f MB",update.size/1048576.0);
                    if(!update.notes.isEmpty()) detail+="\n\n"+update.notes;
                    ThemePolicy.dialog(a).setTitle("发现新版本 "+update.version).setMessage(detail)
                        .setPositiveButton("下载更新",(d,w)->download(a,update))
                        .setNegativeButton("稍后",(d,w)->prefs.edit().putLong("skipped",update.code).apply()).show();
                });
            } catch(Exception e) {
                // Failed background checks stay quiet; retry next launch after one hour.
                prefs.edit().putLong("checked",now-INTERVAL+60*60*1000).apply();
                busy.set(false);
                a.runOnUiThread(() -> { if(manual) message(a,"无法检查更新，请检查网络后重试"); });
            }
        },"app-update-check").start();
    }
    static HttpsURLConnection connect(String url) throws IOException {
        for(int hop=0;hop<5;hop++) {
            if(!UpdatePolicy.allowedUrl(url)) throw new IOException("Untrusted update URL");
            HttpsURLConnection c=(HttpsURLConnection)new URL(url).openConnection();
            c.setUseCaches(false);c.setRequestProperty("Cache-Control","no-cache");
            c.setInstanceFollowRedirects(false); c.setConnectTimeout(15000); c.setReadTimeout(20000);
            c.setRequestProperty("User-Agent","AgentRemote-Android-Updater");
            c.setRequestProperty("Accept","application/vnd.github+json, application/octet-stream");
            int status=c.getResponseCode();
            if(status>=300 && status<400) {
                String next=c.getHeaderField("Location");c.disconnect();
                if(next==null) throw new IOException("Missing redirect");
                url=new URL(new URL(url),next).toString();continue;
            }
            if(status!=200) { c.disconnect();throw new IOException("Update unavailable"); }
            return c;
        }
        throw new IOException("Too many redirects");
    }
    private static String readMetadata() throws IOException {
        HttpsURLConnection c=connect(UpdatePolicy.API);
        try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] b=new byte[8192];int n;
            while((n=in.read(b))!=-1) { if(out.size()+n>2*1024*1024) throw new IOException("Metadata too large");out.write(b,0,n); }
            return out.toString(StandardCharsets.UTF_8.name());
        } finally { c.disconnect(); }
    }
    private static void download(Activity a,UpdatePolicy.Release release) {
        if(!busy.compareAndSet(false,true)) return;
        AtomicBoolean cancelled=new AtomicBoolean();
        ProgressBar progress=new ProgressBar(a,null,android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        AlertDialog dialog=ThemePolicy.dialog(a).setTitle("正在下载 "+release.version).setView(progress)
            .setNegativeButton("取消",(d,w)->cancelled.set(true)).create();
        dialog.setCanceledOnTouchOutside(false);dialog.setOnCancelListener(d->cancelled.set(true));dialog.show();
        new Thread(() -> {
            File dir=new File(a.getCacheDir(),"updates");dir.mkdirs();
            File part=new File(dir,"update.part"),apk=new File(dir,"update.apk");
            HttpsURLConnection c=null;
            try {
                c=connect(release.url);
                try(InputStream in=c.getInputStream();OutputStream out=new FileOutputStream(part)) {
                    transfer(in,out,release,()->cancelled.get() || !alive(a),
                        percent->a.runOnUiThread(()->progress.setProgress(percent)));
                }
                verify(a,part,release.code);
                if(cancelled.get() || !alive(a)) throw new InterruptedIOException();
                if(apk.exists() && !apk.delete()) throw new IOException("Cannot replace cache");
                if(!part.renameTo(apk)) throw new IOException("Cannot save APK");
                a.runOnUiThread(()->{dialog.dismiss();if(alive(a)) offerInstall(a,apk,release.code);});
            } catch(Exception e) {
                part.delete();
                a.runOnUiThread(()->{if(alive(a)){dialog.dismiss();if(!cancelled.get())ThemePolicy.dialog(a)
                    .setTitle("更新未完成").setMessage("下载或校验失败，原版本未改动。请检查网络后重试。")
                    .setPositiveButton("重试",(d,w)->download(a,release)).setNegativeButton("取消",null).show();}});
            } finally { if(c!=null)c.disconnect();busy.set(false); }
        },"app-update-download").start();
    }
    static void transfer(InputStream in,OutputStream out,UpdatePolicy.Release release,
                         java.util.function.BooleanSupplier cancelled,java.util.function.IntConsumer progress) throws Exception {
        MessageDigest hash=MessageDigest.getInstance("SHA-256");long total=0;int last=-1;
        byte[] b=new byte[65536];int n;
        while((n=in.read(b))!=-1) {
            if(cancelled.getAsBoolean()) throw new InterruptedIOException();
            total+=n;if(total>release.size || total>UpdatePolicy.MAX_APK) throw new IOException("Too large");
            hash.update(b,0,n);out.write(b,0,n);
            int percent=(int)(total*100/release.size);
            if(percent!=last) { last=percent;progress.accept(percent); }
        }
        if(cancelled.getAsBoolean()) throw new InterruptedIOException();
        if(total!=release.size || !hex(hash.digest()).equals(release.sha256)) throw new IOException("Checksum mismatch");
    }
    static long version(PackageInfo info) { return Build.VERSION.SDK_INT>=28?info.getLongVersionCode():info.versionCode; }
    static void verify(Activity a,File apk,long expected) throws Exception {
        int flags=Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;
        PackageManager pm=a.getPackageManager();
        PackageInfo installed=pm.getPackageInfo(a.getPackageName(),flags),candidate=pm.getPackageArchiveInfo(apk.getPath(),flags);
        if(candidate==null || !a.getPackageName().equals(candidate.packageName)
            || version(candidate)!=expected || expected<=version(installed)) throw new IOException("Wrong package or version");
        Signature[] old=signatures(installed),next=signatures(candidate);
        if(old==null || next==null || old.length==0 || !new HashSet<>(Arrays.asList(old)).equals(new HashSet<>(Arrays.asList(next))))
            throw new IOException("Signing identity changed");
    }
    private static Signature[] signatures(PackageInfo p) {
        return Build.VERSION.SDK_INT>=28 ? (p.signingInfo==null?null:p.signingInfo.getApkContentsSigners()) : p.signatures;
    }
    private static String hex(byte[] bytes) {
        StringBuilder s=new StringBuilder();for(byte b:bytes)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();
    }
    private static void offerInstall(Activity a,File apk,long code) {
        ThemePolicy.dialog(a).setTitle("更新已下载").setMessage("覆盖安装会保留应用数据。")
            .setPositiveButton("安装",(d,w)->install(a,apk,code)).setNegativeButton("稍后",null).show();
    }
    private static void install(Activity a,File apk,long code) {
        if(!a.getPackageManager().canRequestPackageInstalls()) {
            ThemePolicy.dialog(a).setTitle("允许安装更新")
                .setMessage("在系统设置中允许遥应安装应用，返回后点击“继续安装”。")
                .setPositiveButton("打开设置",(d,w)->{
                    try { a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+a.getPackageName())));
                        ThemePolicy.dialog(a).setTitle("更新已下载").setPositiveButton("继续安装",(x,y)->install(a,apk,code))
                            .setNegativeButton("取消",null).show();
                    } catch(Exception e) { message(a,"无法打开安装权限设置"); }
                }).setNegativeButton("取消",null).show();return;
        }
        try {
            verify(a,apk,code);
            Uri uri=FileProvider.getUriForFile(a,a.getPackageName()+".fileprovider",apk);
            Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.setClipData(ClipData.newRawUri("App update",uri));
            a.startActivity(intent);
        } catch(Exception e) { message(a,"无法安装更新，请重新检查更新"); }
    }
}
