package com.pocketagentdesk.remote;

import android.app.Activity;
import android.content.Context;
import android.content.res.Configuration;
import android.view.View;
import android.widget.TextView;
import android.view.ViewGroup;
import androidx.core.view.WindowCompat;

/** Fixed appearance enum only; no network, credentials or remote JavaScript bridge. */
final class ThemePolicy {
    static boolean valid(String v) { return "system".equals(v)||"light".equals(v)||"dark".equals(v); }
    static String get(Context c) { String v=c.getSharedPreferences("teleply.appearance",0).getString("mode","system"); return valid(v)?v:"system"; }
    static void save(Context c,String v) { if(valid(v)) c.getSharedPreferences("teleply.appearance",0).edit().putString("mode",v).apply(); }
    static boolean dark(Context c) { String v=get(c);return "dark".equals(v)||("system".equals(v)&&(c.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES); }
    static androidx.appcompat.app.AlertDialog.Builder dialog(Context c) {
        return new androidx.appcompat.app.AlertDialog.Builder(c,dark(c)?androidx.appcompat.R.style.Theme_AppCompat_Dialog_Alert:androidx.appcompat.R.style.Theme_AppCompat_Light_Dialog_Alert);
    }
    static void apply(Activity a, View root) {
        boolean dark=dark(a);int bg=dark?0xff000000:0xffffffff;
        a.getWindow().setStatusBarColor(bg);a.getWindow().setNavigationBarColor(bg);
        a.getWindow().setBackgroundDrawable(new android.graphics.drawable.ColorDrawable(bg));
        if(root!=null) root.setBackgroundColor(bg);
        View decor=a.getWindow().getDecorView();
        androidx.core.view.WindowInsetsControllerCompat bars=WindowCompat.getInsetsController(a.getWindow(),decor);
        bars.setAppearanceLightStatusBars(!dark);bars.setAppearanceLightNavigationBars(!dark);
    }
    static void text(View view,boolean dark) {
        if(view instanceof TextView) ((TextView)view).setTextColor(dark?0xffeeeeee:0xff333333);
        if(view instanceof ViewGroup) for(int i=0;i<((ViewGroup)view).getChildCount();i++) text(((ViewGroup)view).getChildAt(i),dark);
    }
}
