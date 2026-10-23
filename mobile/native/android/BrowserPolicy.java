package com.pocketagentdesk.remote;

import java.net.URI;

public final class BrowserPolicy {
    private static URI secure(String url) {
        try {
            URI u = new URI(url);
            return "https".equalsIgnoreCase(u.getScheme()) && u.getHost() != null && u.getUserInfo() == null ? u : null;
        } catch (Exception e) { return null; }
    }
    public static boolean validEntry(String url) {
        URI u = secure(url);
        return u != null && ("/".equals(u.getPath()) || "/account".equals(u.getPath()))
            && u.getQuery() == null && u.getFragment() == null;
    }
    public static boolean externalLink(String entry, String url) {
        return secure(url) != null && !sameOrigin(entry, url);
    }
    public static boolean sameOrigin(String entry, String candidate) {
        URI a = secure(entry), b = secure(candidate);
        return a != null && b != null && a.getHost().equalsIgnoreCase(b.getHost())
            && (a.getPort() == -1 ? 443 : a.getPort()) == (b.getPort() == -1 ? 443 : b.getPort());
    }
}
