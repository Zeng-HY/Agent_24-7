package com.pocketagentdesk.remote;
import org.junit.Test;
import static org.junit.Assert.*;

public class BrowserPolicyTest {
    @Test public void externalLinksAreHttpsWithoutCredentials() {
        String origin="https://relay.example/";
        assertTrue(BrowserPolicy.externalLink(origin,"https://news.example/article?q=1"));
        for(String url:new String[]{"https://relay.example/account","javascript:alert(1)","intent://news.example","file:///private","http://news.example/","https://user:pass@news.example/"})
            assertFalse(url,BrowserPolicy.externalLink(origin,url));
    }
    @Test public void entryMustBeHttpsWithoutCredentialsOrTokens() {
        assertTrue(BrowserPolicy.validEntry("https://8.166.15.235/"));
        assertTrue(BrowserPolicy.validEntry("https://example.com:8443/account"));
        for (String url : new String[] {null, "http://example.com/", "https://user:pass@example.com/",
            "https://example.com/?token=secret", "https://example.com/#invite=secret",
            "javascript:alert(1)", "file:///etc/passwd", "https://example.com/other"}) {
            assertFalse(String.valueOf(url), BrowserPolicy.validEntry(url));
        }
    }
    @Test public void navigationCannotChangeHostPortOrScheme() {
        String origin = "https://example.com/";
        assertTrue(BrowserPolicy.sameOrigin(origin, "https://EXAMPLE.com:443/relay/pair"));
        assertTrue(BrowserPolicy.sameOrigin(origin, "https://example.com/account?next=home"));
        for (String url : new String[] { "https://example.com.evil.test/", "https://example.com:8443/",
            "http://example.com/", "https://example.com@evil.test/", "intent://example.com/", null }) {
            assertFalse(String.valueOf(url), BrowserPolicy.sameOrigin(origin, url));
        }
    }
}
