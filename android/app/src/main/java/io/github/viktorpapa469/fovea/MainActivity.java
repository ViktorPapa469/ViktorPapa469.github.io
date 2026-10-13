package io.github.viktorpapa469.fovea;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.NotificationManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * Fovea for Android: the Fovea web app in a full-screen WebView, plus the phone controls a web page is not allowed to use:
 * Do Not Disturb (after the person grants access once), screen pinning, keeping the screen on and the share sheet.
 * The page talks to the phone through window.FoveaNative.
 */
public class MainActivity extends Activity {
    static final String HOME = "https://viktorpapa469.github.io/";
    static final String HOST = "viktorpapa469.github.io";
    WebView web;
    FrameLayout root;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#18201C"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#18201C"));
        root.addView(web, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);

        // keep the page clear of the status bar, navigation bar and keyboard
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int l, t, r, b;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets s = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime() | WindowInsets.Type.displayCutout());
                l = s.left; t = s.top; r = s.right; b = s.bottom;
            } else {
                l = insets.getSystemWindowInsetLeft(); t = insets.getSystemWindowInsetTop();
                r = insets.getSystemWindowInsetRight(); b = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(l, t, r, b);
            return insets;
        });

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setUserAgentString(s.getUserAgentString() + " FoveaApp/" + version());
        web.addJavascriptInterface(new Bridge(), "FoveaNative");
        web.setWebChromeClient(new WebChromeClient());
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if ("https".equals(u.getScheme()) && HOST.equals(u.getHost())) return false;   // stay inside Fovea
                openOutside(u);
                return true;
            }
        });
        if (saved != null) web.restoreState(saved);
        else web.loadUrl(HOME + "?app=android");
    }

    void openOutside(Uri u) {
        try {
            Intent i = "intent".equals(u.getScheme()) ? Intent.parseUri(u.toString(), Intent.URI_INTENT_SCHEME) : new Intent(Intent.ACTION_VIEW, u);
            startActivity(i);
        } catch (Exception e) { /* nothing on this phone can open it */ }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }

    @Override
    protected void onPause() {
        super.onPause();
        // Tell the page the person has left. The WebView keeps running, so a meditation goes on playing with the screen off.
        web.evaluateJavascript("window.foveaNativeVisible && foveaNativeVisible(false)", null);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.evaluateJavascript("window.foveaNativeVisible && foveaNativeVisible(true)", null);
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        web.evaluateJavascript("(window.foveaBack && foveaBack()) ? 1 : 0", res -> {
            if ("1".equals(res)) return;
            if (web.canGoBack()) web.goBack();
            else moveTaskToBack(true);   // keep the app and any session alive instead of closing it
        });
    }

    String version() {
        try { return getPackageManager().getPackageInfo(getPackageName(), 0).versionName; } catch (Exception e) { return "1.0"; }
    }

    NotificationManager nm() { return (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE); }
    SharedPreferences prefs() { return getSharedPreferences("fovea", MODE_PRIVATE); }

    class Bridge {
        @JavascriptInterface public String platform() { return "android"; }
        @JavascriptInterface public String appVersion() { return version(); }

        @JavascriptInterface public boolean dndAllowed() {
            return Build.VERSION.SDK_INT >= 23 && nm().isNotificationPolicyAccessGranted();
        }

        /** Opens the system page where the person allows Fovea to control Do Not Disturb. */
        @JavascriptInterface public void requestDnd() {
            runOnUiThread(() -> {
                try { startActivity(new Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)); }
                catch (ActivityNotFoundException e) { startActivity(new Intent(Settings.ACTION_SETTINGS)); }
            });
        }

        /** normal = Do Not Disturb (priority only), strict = alarms only. Remembers the previous setting so it can be put back. */
        @JavascriptInterface public boolean setMode(String mode) {
            if (!dndAllowed()) return false;
            NotificationManager n = nm();
            if (!prefs().contains("prevFilter")) prefs().edit().putInt("prevFilter", n.getCurrentInterruptionFilter()).apply();
            n.setInterruptionFilter("strict".equals(mode) ? NotificationManager.INTERRUPTION_FILTER_ALARMS : NotificationManager.INTERRUPTION_FILTER_PRIORITY);
            return true;
        }

        /** Puts Do Not Disturb back the way it was before the session. */
        @JavascriptInterface public void restore() {
            if (!dndAllowed()) return;
            int prev = prefs().getInt("prevFilter", NotificationManager.INTERRUPTION_FILTER_ALL);
            if (prev == NotificationManager.INTERRUPTION_FILTER_UNKNOWN) prev = NotificationManager.INTERRUPTION_FILTER_ALL;
            nm().setInterruptionFilter(prev);
            prefs().edit().remove("prevFilter").apply();
        }

        /** Screen pinning: Android asks the person to confirm, then Home and Recents stay closed until the session ends. */
        @JavascriptInterface public void pin() { runOnUiThread(() -> { try { startLockTask(); } catch (Exception e) {} }); }
        @JavascriptInterface public void unpin() { runOnUiThread(() -> { try { stopLockTask(); } catch (Exception e) {} }); }
        @JavascriptInterface public boolean pinned() {
            ActivityManager am = (ActivityManager) getSystemService(Context.ACTIVITY_SERVICE);
            return Build.VERSION.SDK_INT >= 23 && am.getLockTaskModeState() != ActivityManager.LOCK_TASK_MODE_NONE;
        }

        /** Android does not let apps switch flight mode, so this opens the setting for the person to tap. */
        @JavascriptInterface public void openAirplane() {
            runOnUiThread(() -> { try { startActivity(new Intent(Settings.ACTION_AIRPLANE_MODE_SETTINGS)); } catch (Exception e) {} });
        }

        @JavascriptInterface public void keepAwake(boolean on) {
            runOnUiThread(() -> {
                if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            });
        }

        /** Hides the status and navigation bars during a session. */
        @JavascriptInterface public void immersive(boolean on) {
            runOnUiThread(() -> {
                if (Build.VERSION.SDK_INT >= 30) {
                    WindowInsetsController c = getWindow().getInsetsController();
                    if (c == null) return;
                    if (on) {
                        c.hide(WindowInsets.Type.systemBars());
                        c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                    } else c.show(WindowInsets.Type.systemBars());
                } else {
                    View d = getWindow().getDecorView();
                    d.setSystemUiVisibility(on ? (View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY) : 0);
                }
            });
        }

        @JavascriptInterface public void share(String text) {
            runOnUiThread(() -> {
                Intent i = new Intent(Intent.ACTION_SEND);
                i.setType("text/plain");
                i.putExtra(Intent.EXTRA_TEXT, text);
                startActivity(Intent.createChooser(i, "Share"));
            });
        }
    }
}
