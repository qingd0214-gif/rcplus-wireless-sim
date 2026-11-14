package com.rcplus.dashboard;

/** 顶级类版重试任务：r8 对匿名/内部类有 NPE bug，全部拆成顶级类。 */
public class DashRetryRun implements Runnable {
    private final MainActivity act;

    public DashRetryRun(MainActivity act) { this.act = act; }

    @Override public void run() {
        if (act.isLoadFailed()) act.reloadNow();
    }
}
