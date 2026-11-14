package com.rcplus.dashboard;

import android.graphics.Bitmap;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** 顶级类版 WebViewClient：r8 对匿名/内部类有 NPE bug，全部拆成顶级类。 */
public class DashWebViewClient extends WebViewClient {
    private final MainActivity act;

    public DashWebViewClient(MainActivity act) { this.act = act; }

    @Override public void onPageStarted(WebView v, String u, Bitmap f) {
        act.clearLoadError();
    }

    @Override public void onReceivedError(WebView v, WebResourceRequest req,
                                          WebResourceError err) {
        if (req.isForMainFrame()) act.scheduleRetry();
    }
}
