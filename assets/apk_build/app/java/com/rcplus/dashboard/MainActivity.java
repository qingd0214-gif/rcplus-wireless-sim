package com.rcplus.dashboard;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.view.KeyEvent;
import android.view.WindowManager;
import android.webkit.WebChromeClient;
import android.webkit.WebView;

/**
 * 摇杆仪表 — 全屏 WebView 壳，加载电脑端的仪表网页。
 * URL 优先读 /sdcard/stick_dashboard_url.txt（第一行 http://...），
 * 没有就用编译时写死的默认地址。
 *
 * 自动重试：电脑端手柄脚本可能还没开（或电脑刚开机），
 * 第一次加载失败就停在错误页的话，点图标"没反应"。
 * 现在主页面加载失败后每 3 秒自动重载，直到连上电脑为止；
 * 从后台切回前台（再点一次图标）时若还没连上也立刻重试。
 * 注意：回调类全部用顶级类（DashWebViewClient/DashRetryRun），
 * 匿名/内部类会触发本项目 r8 的 NPE 编译 bug。
 */
public class MainActivity extends Activity {
    private WebView wv;
    private String url;
    private boolean mainFrameError = false;
    private Handler retryHandler;
    private DashRetryRun retryRun;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // 仪表打开期间屏幕不休眠（退出仪表就恢复正常息屏策略）
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);

        wv = new WebView(this);
        wv.getSettings().setJavaScriptEnabled(true);
        wv.getSettings().setDomStorageEnabled(true);
        wv.setWebViewClient(new DashWebViewClient(this));
        wv.setWebChromeClient(new WebChromeClient());
        wv.setBackgroundColor(0xFF0B0F12);
        setContentView(wv);

        url = "http://192.168.31.29:8123";
        try {
            String s = new String(java.nio.file.Files.readAllBytes(
                    java.nio.file.Paths.get("/sdcard/stick_dashboard_url.txt"))).trim();
            if (s.startsWith("http")) url = s;
        } catch (Throwable t) { /* 没有配置文件就用默认地址 */ }
        wv.loadUrl(url);
    }

    // ---- 给回调类用的入口 ----
    void clearLoadError() {
        mainFrameError = false;
        if (retryHandler != null) retryHandler.removeCallbacks(retryRun);
    }

    void scheduleRetry() {
        mainFrameError = true;
        if (retryHandler == null) {
            retryHandler = new Handler();
            retryRun = new DashRetryRun(this);
        }
        retryHandler.removeCallbacks(retryRun);
        retryHandler.postDelayed(retryRun, 3000);
    }

    boolean isLoadFailed() { return mainFrameError; }

    void reloadNow() {
        if (wv != null) wv.loadUrl(url);
    }

    @Override protected void onResume() {
        super.onResume();
        // 之前停在错误页（比如上次打开时电脑还没就绪）→ 回到前台立刻重试
        if (mainFrameError) reloadNow();
    }

    @Override protected void onDestroy() {
        if (retryHandler != null) retryHandler.removeCallbacks(retryRun);
        if (wv != null) wv.destroy();
        super.onDestroy();
    }

    @Override public boolean onKeyDown(int keyCode, KeyEvent event) {
        // 返回键先回退网页，没得退了才退出 App
        if (keyCode == KeyEvent.KEYCODE_BACK && wv != null && wv.canGoBack()) {
            wv.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}
