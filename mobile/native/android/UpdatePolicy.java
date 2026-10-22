package com.pocketagentdesk.remote;

import org.json.JSONArray;
import org.json.JSONObject;
import java.net.URI;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Only this repository's published Android artifacts are update candidates. */
final class UpdatePolicy {
    static final String API = "https://api.github.com/repos/Zeng-HY/Agent_24-7/releases?per_page=30";
    static final String PREFIX = "https://github.com/Zeng-HY/Agent_24-7/releases/download/";
    static final long MAX_APK = 128L * 1024 * 1024;
    private static final Pattern NAME = Pattern.compile("PocketAgentDesk-(\\d+\\.\\d+\\.\\d+)-(\\d+)\\.apk");
    static final class Release {
        final String version, url, sha256, notes;
        final long code, size;
        Release(String version, long code, long size, String url, String sha256, String notes) {
            this.version=version; this.code=code; this.size=size; this.url=url; this.sha256=sha256; this.notes=notes;
        }
    }
    static Release choose(String json, long installed, boolean allowPrerelease) throws Exception {
        JSONArray releases = new JSONArray(json);
        Release best=null;
        for (int i=0;i<releases.length();i++) {
            JSONObject release=releases.getJSONObject(i);
            if (release.optBoolean("draft") || (release.optBoolean("prerelease") && !allowPrerelease)) continue;
            JSONArray assets=release.optJSONArray("assets");
            if (assets==null) continue;
            for(int j=0;j<assets.length();j++) {
                JSONObject asset=assets.getJSONObject(j);
                String name=asset.optString("name"), digest=asset.optString("digest"), url=asset.optString("browser_download_url");
                Matcher m=NAME.matcher(name);
                if (!m.matches() || !digest.matches("sha256:[a-fA-F0-9]{64}")) continue;
                long code;
                try { code=Long.parseLong(m.group(2)); } catch(NumberFormatException e) { continue; }
                long size=asset.optLong("size");
                if(code<=installed || (best!=null && code<=best.code) || size<=0 || size>MAX_APK) continue;
                if(!url.equals(PREFIX+release.optString("tag_name")+"/"+name) || !allowedUrl(url)) continue;
                String notes=release.optString("body", "").trim();
                if(notes.length()>500) notes=notes.substring(0,500)+"…";
                best=new Release(m.group(1),code,size,url,digest.substring(7).toLowerCase(java.util.Locale.ROOT),notes);
            }
        }
        return best;
    }
    static boolean allowedUrl(String value) {
        try {
            URI u=new URI(value);
            if(!"https".equals(u.getScheme()) || u.getUserInfo()!=null || (u.getPort()!=-1 && u.getPort()!=443)) return false;
            String host=u.getHost();
            return ("api.github.com".equals(host) && value.equals(API))
                || ("github.com".equals(host) && value.startsWith(PREFIX) && !u.getPath().contains(".."))
                || "release-assets.githubusercontent.com".equals(host)
                || "objects.githubusercontent.com".equals(host);
        } catch(Exception e) { return false; }
    }
}
