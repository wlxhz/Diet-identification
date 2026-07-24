package com.healthydiet.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.Base64;
import android.util.Pair;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.rokid.cxr.link.CXRLink;
import com.rokid.cxr.link.callbacks.ICXRLinkCbk;
import com.rokid.cxr.link.callbacks.ICXRSessionCbk;
import com.rokid.cxr.link.callbacks.IImageStreamCbk;
import com.rokid.cxr.link.utils.CxrDefs;
import com.rokid.cxr.link.utils.GlassInfo;
import com.rokid.sprite.aiapp.externalapp.auth.AuthResult;
import com.rokid.sprite.aiapp.externalapp.auth.AuthorizationHelper;
import com.rokid.sprite.aiapp.externalapp.auth.GlassPermission;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity
        implements ICXRLinkCbk, ICXRSessionCbk, IImageStreamCbk {

    private static final int AUTHORIZATION_REQUEST = 4101;
    private static final int BLUETOOTH_PERMISSION_REQUEST = 4102;
    private static final long DEFAULT_CAPTURE_INTERVAL_MS = 1200L;

    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService serverExecutor = Executors.newSingleThreadExecutor();
    private final ExecutorService ioExecutor = Executors.newSingleThreadExecutor();

    private WebView webView;
    private CXRLink cxrLink;
    private SharedPreferences preferences;
    private boolean cxrConnected;
    private boolean glassBtConnected;
    private boolean sessionReady;
    private boolean screenOffCaptureAllowed;
    private boolean capturePending;
    private boolean autoCapture;
    private long captureIntervalMs = DEFAULT_CAPTURE_INTERVAL_MS;

    private final Runnable captureLoop = new Runnable() {
        @Override
        public void run() {
            if (!autoCapture) {
                return;
            }
            if (!capturePending) {
                captureFromGlasses();
            }
            mainHandler.postDelayed(this, captureIntervalMs);
        }
    };

    @Override
    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        preferences = getSharedPreferences("rokid_glasses", MODE_PRIVATE);
        cxrLink = ((RokidApplication) getApplication()).getCxrLink();
        configureCxrCallbacks();

        webView = new WebView(this);
        webView.setLayoutParams(new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
        ));
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient());
        webView.addJavascriptInterface(new GlassesJavascriptBridge(), "RokidGlasses");
        setContentView(webView);

        startEmbeddedHealthServer();
    }

    private void configureCxrCallbacks() {
        cxrLink.setCXRLinkCbk(this);
        cxrLink.setCXRImageCbk(this);
        CxrDefs.CXRSession session =
                new CxrDefs.CXRSession(CxrDefs.CXRSessionType.CUSTOMVIEW);
        cxrLink.configCXRSession(session, this);
    }

    private void startEmbeddedHealthServer() {
        serverExecutor.execute(() -> {
            try {
                File resourceDir = new File(getFilesDir(), "web");
                copyAssetTree("web", resourceDir);
                File uploadDir = new File(resourceDir, "static/uploads/avatars");
                if (!uploadDir.exists() && !uploadDir.mkdirs()) {
                    throw new IOException("无法创建头像目录");
                }
                File database = new File(getFilesDir(), "health.db");
                if (!database.exists()) {
                    copyAssetFile("health.db", database);
                }
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(this));
                }
                Python.getInstance()
                        .getModule("android_server")
                        .callAttr(
                                "start",
                                database.getAbsolutePath(),
                                resourceDir.getAbsolutePath(),
                                uploadDir.getAbsolutePath()
                        );
            } catch (Exception error) {
                emitError("本地健康服务启动失败：" + error.getMessage());
            }
        });
        waitForHealthServer(0);
    }

    private void waitForHealthServer(int attempt) {
        ioExecutor.execute(() -> {
            boolean ready = false;
            try {
                HttpURLConnection connection =
                        (HttpURLConnection) new URL("http://127.0.0.1:5000/login").openConnection();
                connection.setConnectTimeout(500);
                connection.setReadTimeout(500);
                connection.setInstanceFollowRedirects(false);
                ready = connection.getResponseCode() > 0;
                connection.disconnect();
            } catch (IOException ignored) {
                // Flask is still starting.
            }
            boolean finalReady = ready;
            mainHandler.post(() -> {
                if (finalReady) {
                    webView.loadUrl("http://127.0.0.1:5000");
                } else if (attempt < 80) {
                    mainHandler.postDelayed(() -> waitForHealthServer(attempt + 1), 250);
                } else {
                    emitError("等待本地健康服务启动超时");
                }
            });
        });
    }

    private void copyAssetTree(String assetPath, File target) throws IOException {
        String[] children = getAssets().list(assetPath);
        if (children == null || children.length == 0) {
            copyAssetFile(assetPath, target);
            return;
        }
        if (!target.exists() && !target.mkdirs()) {
            throw new IOException("无法创建目录：" + target);
        }
        for (String child : children) {
            copyAssetTree(assetPath + "/" + child, new File(target, child));
        }
    }

    private void copyAssetFile(String assetPath, File target) throws IOException {
        File parent = target.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IOException("无法创建目录：" + parent);
        }
        try (InputStream input = getAssets().open(assetPath);
             FileOutputStream output = new FileOutputStream(target)) {
            byte[] buffer = new byte[16 * 1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
            }
        }
    }

    private void requestBluetoothThenAuthorize() {
        if (checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)
                != PackageManager.PERMISSION_GRANTED
                || checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{
                            Manifest.permission.BLUETOOTH_CONNECT,
                            Manifest.permission.BLUETOOTH_SCAN
                    },
                    BLUETOOTH_PERMISSION_REQUEST
            );
            return;
        }
        requestRokidAuthorization();
    }

    private void requestRokidAuthorization() {
        AuthorizationHelper helper = AuthorizationHelper.INSTANCE;
        if (!helper.isRequiredRokidAppInstalled(this)) {
            emitError("请先安装并登录 Rokid AI App，再在其中完成 RV101 蓝牙配对。");
            return;
        }
        if (helper.hasGlassPermission(GlassPermission.CAMERA)) {
            String token = preferences.getString("cxr_token", "");
            if (!token.isEmpty()) {
                connectCxr(token);
                return;
            }
        }
        Pair<Integer, Intent> immediateResult = helper.requestAuthorization(
                this,
                new GlassPermission[]{GlassPermission.CAMERA},
                AUTHORIZATION_REQUEST
        );
        if (immediateResult != null) {
            handleAuthorizationResult(immediateResult.first, immediateResult.second);
        } else {
            emitState("等待 Rokid AI App 授予眼镜相机权限");
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != AUTHORIZATION_REQUEST) {
            return;
        }
        handleAuthorizationResult(resultCode, data);
    }

    private void handleAuthorizationResult(int resultCode, Intent data) {
        AuthResult result = AuthorizationHelper.INSTANCE
                .parseAuthorizationResult(resultCode, data);
        if (result instanceof AuthResult.AuthSuccess) {
            String token = ((AuthResult.AuthSuccess) result).getToken();
            preferences.edit().putString("cxr_token", token).apply();
            try {
                connectCxr(token);
            } catch (RuntimeException error) {
                emitError("Rokid 眼镜连接初始化失败：" + error.getMessage());
            }
        } else if (result instanceof AuthResult.AuthCancel) {
            emitError("已取消 Rokid 眼镜授权");
        } else {
            emitError("Rokid 眼镜授权失败，请回到 Rokid AI App 检查配对状态");
        }
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != BLUETOOTH_PERMISSION_REQUEST) {
            return;
        }
        boolean granted = true;
        for (int result : grantResults) {
            granted &= result == PackageManager.PERMISSION_GRANTED;
        }
        if (granted) {
            requestRokidAuthorization();
        } else {
            emitError("需要附近设备权限才能通过 Rokid AI App 连接眼镜");
        }
    }

    private void connectCxr(String token) {
        configureCxrCallbacks();
        CxrDefs.CXRSessionState currentState = cxrLink.getCXRSessionState();
        if (currentState != CxrDefs.CXRSessionState.SessionUnavailable) {
            cxrConnected = true;
            glassBtConnected = cxrLink.isGlassBtConnected();
            sessionReady = currentState == CxrDefs.CXRSessionState.SessionAvailable
                    || currentState == CxrDefs.CXRSessionState.SessionStart;
            screenOffCaptureAllowed =
                    currentState == CxrDefs.CXRSessionState.SessionPause;
            if (isCameraCaptureAllowed()) {
                emitState(sessionReady
                        ? "Rokid 眼镜已连接，相机会话可用"
                        : "Rokid 眼镜已连接，熄屏摄像模式可用");
                return;
            }
        }
        boolean accepted = cxrLink.connect(token);
        emitState(accepted ? "正在连接 Rokid AI App 与眼镜" : "CXR-L 拒绝了连接请求");
    }

    private void captureFromGlasses() {
        if (!isCameraCaptureAllowed()) {
            emitError("眼镜摄像链路尚未就绪，请先完成 Rokid AI App 蓝牙配对与授权");
            return;
        }
        capturePending = cxrLink.takePhoto(1280, 720, 82);
        if (!capturePending) {
            emitError("眼镜未接受拍照请求");
        } else {
            emitState("正在从 RV101 获取照片");
        }
    }

    private boolean isCameraCaptureAllowed() {
        return cxrConnected
                && glassBtConnected
                && (sessionReady || screenOffCaptureAllowed);
    }

    private void uploadForAnalysis(byte[] jpeg) {
        ioExecutor.execute(() -> {
            HttpURLConnection connection = null;
            try {
                String baseUrl = preferences.getString(
                        "analysis_server",
                        "http://192.168.1.100:9088"
                );
                URL url = new URL(baseUrl.replaceAll("/+$", "") + "/api/analyze");
                connection = (HttpURLConnection) url.openConnection();
                connection.setRequestMethod("POST");
                connection.setConnectTimeout(5000);
                connection.setReadTimeout(30000);
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "image/jpeg");
                connection.setRequestProperty("X-Device-Name", "Rokid-RV101");
                connection.setFixedLengthStreamingMode(jpeg.length);
                connection.getOutputStream().write(jpeg);

                int status = connection.getResponseCode();
                InputStream stream = status >= 400
                        ? connection.getErrorStream()
                        : connection.getInputStream();
                String payload = readText(stream);
                if (status >= 400) {
                    throw new IOException("识别服务返回 " + status + "：" + payload);
                }
                emitAnalysis(payload);
            } catch (Exception error) {
                emitError("眼镜照片上传失败：" + error.getMessage());
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    private String readText(InputStream input) throws IOException {
        if (input == null) {
            return "";
        }
        StringBuilder result = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                result.append(line);
            }
        }
        return result.toString();
    }

    private JSONObject stateJson(String message) {
        JSONObject state = new JSONObject();
        try {
            state.put("cxr_connected", cxrConnected);
            state.put("glass_bt_connected", glassBtConnected);
            state.put("session_ready", sessionReady);
            state.put("ready", isCameraCaptureAllowed());
            state.put("auto_capture", autoCapture);
            state.put("capture_pending", capturePending);
            state.put("server_url", preferences.getString(
                    "analysis_server",
                    "http://192.168.1.100:9088"
            ));
            state.put("message", message);
        } catch (JSONException ignored) {
            // The fields above are primitive and cannot fail in normal use.
        }
        return state;
    }

    private void emitState(String message) {
        String quoted = JSONObject.quote(stateJson(message).toString());
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onState(" + quoted + ")"
        );
    }

    private void emitAnalysis(String payload) {
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onAnalysis("
                        + JSONObject.quote(payload) + ")"
        );
    }

    private void emitFrame(byte[] jpeg) {
        String dataUrl = "data:image/jpeg;base64,"
                + Base64.encodeToString(jpeg, Base64.NO_WRAP);
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onFrame("
                        + JSONObject.quote(dataUrl) + ")"
        );
    }

    private void emitError(String message) {
        evaluateJavascript(
                "window.RokidGlassesEvents&&window.RokidGlassesEvents.onError("
                        + JSONObject.quote(message) + ")"
        );
    }

    private void evaluateJavascript(String script) {
        mainHandler.post(() -> {
            if (webView != null) {
                webView.evaluateJavascript(script, null);
            }
        });
    }

    @Override
    public void onCXRLConnected(boolean connected) {
        cxrConnected = connected;
        if (!connected) {
            sessionReady = false;
            screenOffCaptureAllowed = false;
        }
        emitState(connected ? "CXR-L 服务已连接" : "CXR-L 服务已断开");
    }

    @Override
    public void onGlassBtConnected(boolean connected) {
        glassBtConnected = connected;
        if (!connected) {
            sessionReady = false;
            screenOffCaptureAllowed = false;
        }
        emitState(connected ? "RV101 蓝牙已连接" : "RV101 蓝牙未连接");
    }

    @Override
    public void onGlassDeviceInfo(GlassInfo info) {
        emitState("眼镜：" + info.deviceName + " · 电量 " + info.batteryLevel + "%");
    }

    @Override
    public void onGlassWearingStatus(boolean wearing) {
        emitState(wearing ? "眼镜佩戴中" : "眼镜未佩戴");
    }

    @Override
    public void onGlassAiAssistStart() {
        emitState("眼镜 AI 助手正在占用会话");
    }

    @Override
    public void onGlassAiAssistStop() {
        emitState("眼镜 AI 助手已释放会话");
    }

    @Override
    public void onGlassAiInterrupt(boolean interrupted) {
        emitState(interrupted ? "眼镜会话被打断" : "眼镜会话已恢复");
    }

    @Override
    public void onSessionAvailable(CxrDefs.CXRSessionReason reason) {
        sessionReady = true;
        screenOffCaptureAllowed = false;
        emitState("眼镜相机会话可用");
    }

    @Override
    public void onSessionStart(CxrDefs.CXRSessionReason reason) {
        sessionReady = true;
        screenOffCaptureAllowed = false;
        emitState("眼镜相机会话已就绪");
    }

    @Override
    public void onSessionPause(CxrDefs.CXRSessionReason reason) {
        sessionReady = false;
        screenOffCaptureAllowed =
                reason == CxrDefs.CXRSessionReason.SESSION_SCREEN_OFF;
        emitState(screenOffCaptureAllowed
                ? "眼镜已熄屏，摄像头后台采集保持可用"
                : "眼镜相机会话暂停：" + reason);
    }

    @Override
    public void onSessionUnavailable(CxrDefs.CXRSessionReason reason) {
        sessionReady = false;
        screenOffCaptureAllowed = false;
        emitState("眼镜相机会话不可用：" + reason);
    }

    @Override
    public void onImageReceived(byte[] jpeg) {
        capturePending = false;
        if (jpeg == null || jpeg.length == 0) {
            emitError("眼镜返回了空图片，请重试");
            return;
        }
        emitFrame(jpeg);
        emitState("已收到 RV101 照片，正在识别");
        uploadForAnalysis(jpeg);
    }

    @Override
    public void onImageError(int code, String message) {
        capturePending = false;
        emitError("眼镜拍照失败（" + code + "）：" + message);
    }

    @Override
    protected void onDestroy() {
        autoCapture = false;
        mainHandler.removeCallbacks(captureLoop);
        cxrLink.disconnect();
        serverExecutor.shutdownNow();
        ioExecutor.shutdownNow();
        if (webView != null) {
            webView.destroy();
        }
        super.onDestroy();
    }

    public final class GlassesJavascriptBridge {
        @JavascriptInterface
        public void requestAuthorizationAndConnect() {
            runOnUiThread(MainActivity.this::requestBluetoothThenAuthorize);
        }

        @JavascriptInterface
        public void capture() {
            runOnUiThread(MainActivity.this::captureFromGlasses);
        }

        @JavascriptInterface
        public void startAutoCapture(long intervalMs) {
            runOnUiThread(() -> {
                captureIntervalMs = Math.max(700L, Math.min(intervalMs, 5000L));
                autoCapture = true;
                mainHandler.removeCallbacks(captureLoop);
                mainHandler.post(captureLoop);
                emitState("已开始眼镜低频连续采集");
            });
        }

        @JavascriptInterface
        public void stopAutoCapture() {
            runOnUiThread(() -> {
                autoCapture = false;
                mainHandler.removeCallbacks(captureLoop);
                emitState("已停止眼镜采集");
            });
        }

        @JavascriptInterface
        public String getState() {
            return stateJson("当前眼镜状态").toString();
        }

        @JavascriptInterface
        public String getServerUrl() {
            return preferences.getString(
                    "analysis_server",
                    "http://192.168.1.100:9088"
            );
        }

        @JavascriptInterface
        public boolean setServerUrl(String url) {
            if (url == null || !url.matches("^https?://[^\\s/]+(?::\\d+)?/?$")) {
                return false;
            }
            preferences.edit()
                    .putString("analysis_server", url.replaceAll("/+$", ""))
                    .apply();
            emitState("识别服务地址已保存");
            return true;
        }
    }
}
