#!/usr/bin/env python3
"""build.py — 一键重建 StickDashboard.apk（无需 Android Studio）

流水线: aapt2 compile → aapt2 link → javac → d8 → 打包 dex → apksigner 签名
工具: apk_build/bt/android-14（build-tools 34）+ android.jar（platform-34-ext11）
签名: rcplus.keystore / alias rcplus / 密码 rcplus123
产出: StickDashboard.apk，用 adb install -r 装到遥控器
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BT = HERE / "bt" / "android-14"
JAVA = Path(r"C:/tools/jdk21/bin")
JAVAC = str(JAVA / "javac.exe")

# d8/apksigner 是 bat，需要像样的 JVM；PATH 里的 java 是 1.6，跑不动 r8
ENV = os.environ.copy()
ENV["JAVA_HOME"] = str(JAVA.parent)
ENV["PATH"] = str(JAVA) + os.pathsep + ENV["PATH"]
ENV["ANDROID_ADB_SERVER_PORT"] = "5038"   # 和手柄脚本共用同一个 adb server


def run(label, *cmd, bat=False):
    print(f">> {label}")
    if bat:
        cmd = ["cmd", "/c", *cmd]
    r = subprocess.run(cmd, env=ENV, cwd=str(HERE), capture_output=True,
                       text=True, encoding="gbk", errors="replace")
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        sys.exit(f"[!] {label} 失败 (码 {r.returncode})")
    if r.stdout.strip():
        print("   " + r.stdout.strip().splitlines()[-1])
    return r


def main():
    # 1) 编译资源
    run("aapt2 compile", str(BT / "aapt2.exe"), "compile",
        "--dir", str(HERE / "app/res"), "-o", "res.zip")

    # 2) 链接资源 → 基础 apk（含 manifest/assets/icon）
    run("aapt2 link", str(BT / "aapt2.exe"), "link",
        "-o", "base.apk", "-I", "android.jar",
        "--manifest", "app/AndroidManifest.xml",
        "--min-sdk-version", "24", "--target-sdk-version", "28",
        "-A", "app/assets", "res.zip")

    # 3) 编译 Java
    classes = HERE / "classes"
    if classes.exists():
        shutil.rmtree(classes)
    sources = [str(p) for p in (HERE / "app/java").rglob("*.java")]
    run("javac", JAVAC, "-encoding", "UTF-8", "-source", "8", "-target", "8",
        "-Xlint:-options", "-bootclasspath", "android.jar",
        "-d", "classes", *sources)

    # 4) dex（d8 对散装 .class 会 NPE，先打成 jar 再喂）
    jar_exe = str(JAVA.parent / "bin" / "jar.exe")
    run("jar", jar_exe, "cf", "classes.jar", "-C", "classes", ".")
    dex_out = HERE / "dex_out"
    if dex_out.exists():
        shutil.rmtree(dex_out)
    dex_out.mkdir()
    run("d8", str(BT / "d8.bat"), "--release", "--min-api", "24",
        "--lib", "android.jar", "--output", "dex_out", "classes.jar", bat=True)

    # 5) 把 classes.dex 塞进 apk
    unsigned = HERE / "unsigned.apk"
    shutil.copy("base.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a") as z:
        z.write(dex_out / "classes.dex", "classes.dex")
    print(f">> 打包完成: {unsigned.stat().st_size} bytes")

    # 6) 签名
    run("apksigner", str(BT / "apksigner.bat"), "sign",
        "--ks", "rcplus.keystore", "--ks-key-alias", "rcplus",
        "--ks-pass", "pass:rcplus123", "--key-pass", "pass:rcplus123",
        "--out", "StickDashboard.apk", "unsigned.apk", bat=True)
    run("verify", str(BT / "apksigner.bat"), "verify", "StickDashboard.apk",
        bat=True)

    apk = HERE / "StickDashboard.apk"
    print(f"\n★ 产物: {apk}  ({apk.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
