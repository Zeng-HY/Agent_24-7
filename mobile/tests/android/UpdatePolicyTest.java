package com.pocketagentdesk.remote;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.robolectric.RobolectricTestRunner;
import org.robolectric.annotation.Config;
import static org.junit.Assert.*;
import android.app.Activity;
import android.content.pm.PackageInfo;
import android.content.pm.Signature;
import android.content.pm.SigningInfo;
import org.robolectric.Robolectric;
import static org.robolectric.Shadows.shadowOf;
import java.io.File;

@RunWith(RobolectricTestRunner.class)
@Config(sdk=35)
public class UpdatePolicyTest {
    private JSONObject release(int code,boolean preview) throws Exception {
        String name="PocketAgentDesk-0.5.0-"+code+".apk";
        JSONObject asset=new JSONObject().put("name",name).put("size",12345)
            .put("digest","sha256:"+"a".repeat(64))
            .put("browser_download_url",UpdatePolicy.PREFIX+"android-v0.5.0/"+name);
        return new JSONObject().put("tag_name","android-v0.5.0").put("prerelease",preview)
            .put("assets",new JSONArray().put(asset));
    }
    @Test public void onlyHigherVersionAndCorrectChannelAreOffered() throws Exception {
        String feed=new JSONArray().put(release(6,true)).put(release(5,false)).toString();
        assertEquals(5,UpdatePolicy.choose(feed,4,false).code);
        assertEquals(6,UpdatePolicy.choose(feed,4,true).code);
        assertNull(UpdatePolicy.choose(feed,6,true));
        JSONObject draft=release(7,false).put("draft",true);
        assertNull(UpdatePolicy.choose(new JSONArray().put(draft).toString(),4,true));
    }
    @Test public void refusesTamperedOrUnverifiableArtifacts() throws Exception {
        for(String field:new String[]{"digest","size","browser_download_url","name"}) {
            JSONObject r=release(5,false),asset=r.getJSONArray("assets").getJSONObject(0);
            asset.put(field,field.equals("size")?UpdatePolicy.MAX_APK+1:"invalid");
            assertNull(field,UpdatePolicy.choose(new JSONArray().put(r).toString(),4,true));
        }
    }
    @Test public void selectsByVersionNotReleaseDateAndIgnoresWindowsAssets() throws Exception {
        JSONObject windows=new JSONObject().put("assets",new JSONArray().put(new JSONObject().put("name","Setup.exe")));
        assertEquals(8,UpdatePolicy.choose(new JSONArray().put(release(5,false)).put(windows).put(release(8,false)).toString(),4,false).code);
    }
    @Test public void rejectsInsecureRedirectsAndOtherRepositories() {
        assertTrue(UpdatePolicy.allowedUrl(UpdatePolicy.API));
        assertTrue(UpdatePolicy.allowedUrl("https://release-assets.githubusercontent.com/file?token=example"));
        assertFalse(UpdatePolicy.allowedUrl("http://github.com/Zeng-HY/Agent_24-7/releases/download/v/a.apk"));
        assertFalse(UpdatePolicy.allowedUrl("https://github.com/other/repo/releases/download/v/a.apk"));
        assertFalse(UpdatePolicy.allowedUrl("https://github.com.evil.test/Zeng-HY/Agent_24-7/releases/download/v/a.apk"));
        assertFalse(UpdatePolicy.allowedUrl("https://user:password@release-assets.githubusercontent.com/a"));
        assertFalse(UpdatePolicy.allowedUrl("https://release-assets.githubusercontent.com:8443/a"));
    }
    @Test public void archiveMustMatchInstalledIdentityAndAdvertisedHigherVersion() throws Exception {
        try(var controller=Robolectric.buildActivity(Activity.class).setup()) {
            Activity activity=controller.get();
            var pm=activity.getPackageManager();
            PackageInfo installed=pm.getPackageInfo(activity.getPackageName(),0);
            installed.setLongVersionCode(4);
            installed.signingInfo=new SigningInfo();
            shadowOf(installed.signingInfo).setSignatures(new Signature[]{new Signature("1234")});
            shadowOf(pm).installPackage(installed);
            File file=new File(activity.getCacheDir(),"candidate.apk");
            PackageInfo candidate=new PackageInfo();candidate.packageName=activity.getPackageName();candidate.setLongVersionCode(5);
            candidate.signingInfo=new SigningInfo();
            shadowOf(candidate.signingInfo).setSignatures(new Signature[]{new Signature("1234")});
            shadowOf(pm).setPackageArchiveInfo(file.getPath(),candidate);
            AppUpdater.verify(activity,file,5);
            assertThrows(java.io.IOException.class,()->AppUpdater.verify(activity,file,6));
            candidate.setLongVersionCode(4);
            assertThrows(java.io.IOException.class,()->AppUpdater.verify(activity,file,4));
            candidate.setLongVersionCode(5);candidate.packageName="another.app";
            assertThrows(java.io.IOException.class,()->AppUpdater.verify(activity,file,5));
            candidate.packageName=activity.getPackageName();
            shadowOf(candidate.signingInfo).setSignatures(new Signature[]{new Signature("5678")});
            assertThrows(java.io.IOException.class,()->AppUpdater.verify(activity,file,5));
        }
    }
    @Test public void boundedDownloadRejectsTruncationTamperingOverflowAndCancellation() throws Exception {
        byte[] body="abc".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        var release=new UpdatePolicy.Release("0.5.0",5,3,"unused",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"," ");
        var out=new java.io.ByteArrayOutputStream();
        var progress=new java.util.ArrayList<Integer>();
        AppUpdater.transfer(new java.io.ByteArrayInputStream(body),out,release,()->false,progress::add);
        assertArrayEquals(body,out.toByteArray());assertEquals(Integer.valueOf(100),progress.get(progress.size()-1));
        for(byte[] invalid:new byte[][]{new byte[]{97,98},new byte[]{97,98,100},new byte[]{97,98,99,100}}) {
            assertThrows(java.io.IOException.class,()->AppUpdater.transfer(new java.io.ByteArrayInputStream(invalid),
                new java.io.ByteArrayOutputStream(),release,()->false,p->{}));
        }
        assertThrows(java.io.InterruptedIOException.class,()->AppUpdater.transfer(new java.io.ByteArrayInputStream(body),
            new java.io.ByteArrayOutputStream(),release,()->true,p->{}));
    }
}
